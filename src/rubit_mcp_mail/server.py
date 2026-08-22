"""MCP tool surface.

Every tool here is read-only; all are annotated read_only_hint=True so a client
can see that at a glance. Errors are returned as readable strings rather than
tracebacks, because the model is the one reading them.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .mime import DEFAULT_MAX_CHARS
from .models import AccountStatus, StaleHandleError
from .session import Session

log = logging.getLogger(__name__)

mcp = MCPServer(
    name="rubit-mcp-mail",
    instructions=(
        "Read-only access to the user's mailboxes over IMAP. Use list_folders to "
        "discover folders (referred to by normalized roles such as 'inbox', 'sent', "
        "'junk'), list_messages to browse and search_messages to find mail. Both "
        "return opaque handles; pass a handle to read_message for the full body. "
        "Reading never marks mail as read and nothing in the mailbox can be modified."
    ),
)

_session = Session()

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)

AccountArg = Annotated[
    str | None,
    Field(default=None, description="Account name. Optional when only one is configured."),
]
FolderArg = Annotated[
    str,
    Field(
        default="inbox",
        description="Folder role ('inbox', 'sent', 'junk', 'trash', 'drafts', 'archive') "
        "or a raw server folder name.",
    ),
]
LimitArg = Annotated[int, Field(default=25, ge=1, le=200, description="Max messages to return.")]
OffsetArg = Annotated[int, Field(default=0, ge=0, description="Messages to skip, for paging.")]


def _fail(exc: Exception) -> str:
    """Turn an exception into something the model can act on."""
    return f"Error: {exc}"


@mcp.tool(annotations=READ_ONLY)
def list_accounts() -> list[AccountStatus] | str:
    """List configured mail accounts and whether each is authenticated.

    Call this first if another tool reports an authentication problem.
    """
    try:
        config = _session.config
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)

    out: list[AccountStatus] = []
    for account in config.accounts.values():
        try:
            state, detail = _session.auth_for(account).status()
        except Exception as exc:  # noqa: BLE001
            state, detail = "error", str(exc)
        out.append(
            AccountStatus(
                name=account.name,
                provider=account.provider,
                email=account.email,
                auth=state,  # type: ignore[arg-type]
                detail=detail,
            )
        )
    return out


@mcp.tool(annotations=READ_ONLY)
def list_folders(account: AccountArg = None) -> list[dict[str, Any]] | str:
    """List the folders in a mailbox with message and unread counts.

    Each folder has a normalized `role` that is stable across providers, so you
    can ask for 'junk' without knowing the server calls it 'Junk Email'.
    """
    try:
        folders = _session.backend(account).list_folders()
        return [f.model_dump() for f in folders]
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(annotations=READ_ONLY)
def list_messages(
    account: AccountArg = None,
    folder: FolderArg = "inbox",
    limit: LimitArg = 25,
    offset: OffsetArg = 0,
    unread_only: Annotated[bool, Field(default=False, description="Only unread mail.")] = False,
) -> list[dict[str, Any]] | str:
    """Browse messages in a folder, newest first.

    Returns summaries only (no bodies). Pass a returned `handle` to read_message
    to get the full text.
    """
    try:
        messages = _session.backend(account).list_messages(
            folder=folder, limit=limit, offset=offset, unread_only=unread_only
        )
        return [m.model_dump(by_alias=True, mode="json") for m in messages]
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(annotations=READ_ONLY)
def search_messages(
    account: AccountArg = None,
    folder: FolderArg = "inbox",
    text: Annotated[
        str | None, Field(default=None, description="Free text, matched against headers and body.")
    ] = None,
    from_: Annotated[
        str | None, Field(default=None, description="Substring of the sender address or name.")
    ] = None,
    subject: Annotated[str | None, Field(default=None, description="Substring of the subject.")] = None,
    since: Annotated[date | None, Field(default=None, description="On or after this date.")] = None,
    before: Annotated[date | None, Field(default=None, description="Strictly before this date.")] = None,
    unread_only: Annotated[bool, Field(default=False, description="Only unread mail.")] = False,
    limit: LimitArg = 25,
    offset: OffsetArg = 0,
) -> list[dict[str, Any]] | str:
    """Search a folder. All supplied criteria are combined with AND.

    Server-side IMAP search, so it works over the whole folder without
    downloading anything. Results are newest first.
    """
    try:
        messages = _session.backend(account).search_messages(
            folder=folder,
            text=text,
            from_=from_,
            subject=subject,
            since=since,
            before=before,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
        return [m.model_dump(by_alias=True, mode="json") for m in messages]
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(annotations=READ_ONLY)
def read_message(
    handle: Annotated[str, Field(description="A handle from list_messages or search_messages.")],
    account: AccountArg = None,
    max_chars: Annotated[
        int,
        Field(
            default=DEFAULT_MAX_CHARS,
            ge=200,
            le=200_000,
            description="Truncate the body beyond this many characters.",
        ),
    ] = DEFAULT_MAX_CHARS,
) -> dict[str, Any] | str:
    """Read one message in full: headers, body text, and attachment metadata.

    HTML-only mail is converted to text. This does NOT mark the message as read.
    """
    try:
        message = _session.backend(account).read_message(handle, max_chars=max_chars)
        return message.model_dump(by_alias=True, mode="json")
    except StaleHandleError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(annotations=READ_ONLY)
def get_attachment(
    handle: Annotated[str, Field(description="A handle from list_messages or search_messages.")],
    part_id: Annotated[str, Field(description="The `part_id` from read_message's attachments.")],
    account: AccountArg = None,
) -> dict[str, Any] | str:
    """Download one attachment into the configured download directory.

    Returns the path it was saved to. Files are only ever written inside that
    one directory; the mailbox itself is not modified.
    """
    try:
        backend = _session.backend(account)
        filename, data = backend.fetch_attachment(handle, part_id)
        path = _session.download_path(filename)
        path.write_bytes(data)
        return {"path": str(path), "filename": path.name, "bytes": len(data)}
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    mcp.run(transport="stdio")
