"""MCP tool surface.

Every tool here is read-only; all are annotated read_only_hint=True so a client
can see that at a glance. Errors are returned as readable strings rather than
tracebacks, because the model is the one reading them.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .config import config_path
from .mime import DEFAULT_MAX_CHARS
from .models import AccountStatus, StaleHandleError
from .permissions import TOOL_NAMES, WRITE_TOOL_NAMES
from .session import Session

log = logging.getLogger(__name__)

mcp = MCPServer(
    name="rubit-mcp-mail",
    instructions=(
        "Access to the user's mailboxes over IMAP. Use list_folders to discover "
        "folders (referred to by normalized roles such as 'inbox', 'sent', 'junk'), "
        "list_messages to browse and search_messages to find mail. Both return "
        "opaque handles; pass a handle to read_message for the full body. Reading "
        "never marks mail as read. mark_read and move_message can modify a mailbox "
        "but are disabled per account by default - they only work for an account "
        "where write access has been explicitly turned on in the permissions UI "
        "(`rubit-mcp-mail permissions`), and even then only if that specific tool "
        "was enabled; otherwise they return an error explaining which switch is off. "
        "There is no way to delete or trash mail through this server."
    ),
)

_session = Session()

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)
MARK_READ = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
MOVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

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


def guarded(fn):
    """Block a tool call for an account that has it in `disabled_tools`.

    If the account can't be resolved (missing config, unknown/ambiguous
    name), defers to the wrapped function so its own error message is what
    the model sees - this only adds a new failure mode, never removes one.
    """
    assert fn.__name__ in TOOL_NAMES, f"{fn.__name__!r} is not in permissions.TOOL_NAMES"

    @functools.wraps(fn)
    def wrapper(**kwargs):
        try:
            account = _session.account(kwargs.get("account"))
        except Exception:  # noqa: BLE001
            return fn(**kwargs)
        if fn.__name__ in account.disabled_tools:
            return _fail(ValueError(f"{fn.__name__!r} is disabled for account {account.name!r}"))
        return fn(**kwargs)

    return wrapper


def guarded_write(fn):
    """Block a write tool call unless the account has opted into it.

    Unlike `guarded`, this is opt-in: the account must both have
    `allow_write` on (the parent switch) and list this tool in
    `enabled_write_tools`. Same pass-through-on-unresolvable-account
    behavior as `guarded`.
    """
    assert fn.__name__ in WRITE_TOOL_NAMES, (
        f"{fn.__name__!r} is not in permissions.WRITE_TOOL_NAMES"
    )

    @functools.wraps(fn)
    def wrapper(**kwargs):
        try:
            account = _session.account(kwargs.get("account"))
        except Exception:  # noqa: BLE001
            return fn(**kwargs)
        if not account.allow_write:
            return _fail(
                ValueError(
                    f"Write access is disabled for account {account.name!r}. Enable "
                    "it (and this tool) in the permissions UI (`rubit-mcp-mail "
                    "permissions`) to allow it."
                )
            )
        if fn.__name__ not in account.enabled_write_tools:
            return _fail(ValueError(f"{fn.__name__!r} is disabled for account {account.name!r}"))
        return fn(**kwargs)

    return wrapper


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
@guarded
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
@guarded
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
@guarded
def search_messages(
    account: AccountArg = None,
    folder: FolderArg = "inbox",
    text: Annotated[
        str | None, Field(default=None, description="Free text, matched against headers and body.")
    ] = None,
    from_: Annotated[
        str | None, Field(default=None, description="Substring of the sender address or name.")
    ] = None,
    subject: Annotated[
        str | None, Field(default=None, description="Substring of the subject.")
    ] = None,
    since: Annotated[date | None, Field(default=None, description="On or after this date.")] = None,
    before: Annotated[
        date | None, Field(default=None, description="Strictly before this date.")
    ] = None,
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
@guarded
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
@guarded
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


@mcp.tool(annotations=MARK_READ)
@guarded_write
def mark_read(
    handle: Annotated[str, Field(description="A handle from list_messages or search_messages.")],
    account: AccountArg = None,
) -> dict[str, Any] | str:
    """Mark one message as read (sets the \\Seen flag).

    Disabled by default: the account needs write access and this specific
    tool enabled in the permissions UI (`rubit-mcp-mail permissions`).
    """
    try:
        _session.backend(account).mark_read(handle)
        return {"handle": handle, "seen": True}
    except StaleHandleError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool(annotations=MOVE)
@guarded_write
def move_message(
    handle: Annotated[str, Field(description="A handle from list_messages or search_messages.")],
    folder: Annotated[
        str,
        Field(
            description="Destination folder role ('inbox', 'sent', 'junk', 'trash', "
            "'drafts', 'archive') or a raw server folder name."
        ),
    ],
    account: AccountArg = None,
) -> dict[str, Any] | str:
    """Move one message to another folder.

    The message's handle is stale immediately afterwards - re-run
    list_messages or search_messages against the destination folder to get a
    fresh handle for it. Disabled by default: the account needs write access
    and this specific tool enabled in the permissions UI
    (`rubit-mcp-mail permissions`).
    """
    try:
        destination = _session.backend(account).move_message(handle, folder)
        return {"moved_to": destination}
    except StaleHandleError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def _configure_logging() -> None:
    """Set up stderr logging for the server.

    stdout is the MCP transport and must stay clean, so everything goes to
    stderr - which the MCP client captures (Claude Desktop writes it to
    ~/.config/Claude/logs/mcp-server-<name>.log). RUBIT_MCP_MAIL_LOG_LEVEL
    raises the verbosity without needing a CLI flag, since MCP clients launch
    the server with a fixed argv.
    """
    requested = os.environ.get("RUBIT_MCP_MAIL_LOG_LEVEL")
    if requested:
        level = getattr(logging, requested.upper(), logging.INFO)
    else:
        # `-v` on the CLI has already put the root logger at DEBUG; otherwise
        # INFO, so the startup summary below is always in the client's log.
        level = min(logging.root.level or logging.INFO, logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if path := os.environ.get("RUBIT_MCP_MAIL_LOG_FILE"):
        handlers.append(logging.FileHandler(Path(path).expanduser(), encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,  # replace whatever __main__ installed before dispatching here
    )


def _log_startup() -> None:
    """Report where the server is reading config and credentials from.

    `serve` is launched by a GUI client with a stripped environment, so it can
    easily resolve a different config path - or a different secret backend -
    than the CLI the user ran `auth` from. That mismatch looks exactly like an
    expired token, so say it out loud at startup.
    """
    log.info("rubit-mcp-mail serve starting (pid %s)", os.getpid())
    log.info(
        "env: HOME=%s XDG_CONFIG_HOME=%s DBUS_SESSION_BUS_ADDRESS=%s",
        os.environ.get("HOME"),
        os.environ.get("XDG_CONFIG_HOME", "<unset>"),
        os.environ.get("DBUS_SESSION_BUS_ADDRESS", "<unset>"),
    )

    path = config_path()
    log.info("config: %s (%s)", path, "found" if path.exists() else "MISSING")
    log.info("secrets: %s", _session.store.backend_name)
    if reason := _session.store.unavailable_reason:
        log.warning(
            "OS keyring not in use: %s. Credentials stored by `rubit-mcp-mail auth` "
            "in the keyring will NOT be visible to this process.",
            reason,
        )

    try:
        accounts = list(_session.config.accounts.values())
    except Exception as exc:  # noqa: BLE001 - never let diagnostics stop the server
        log.warning("could not load config: %s", exc)
        return

    for account in accounts:
        try:
            strategy = _session.auth_for(account)
            stored = _session.store.get(strategy.secret_key) is not None
            log.info(
                "account %s <%s> via %s: credential %s (key %r)",
                account.name,
                account.email,
                account.provider,
                "present" if stored else "NOT FOUND",
                strategy.secret_key,
            )
            # status() can refresh over the network; only pay for that when
            # someone has actually asked for debug output.
            if log.isEnabledFor(logging.DEBUG):
                state, detail = strategy.status()
                log.debug(
                    "account %s auth status: %s%s",
                    account.name,
                    state,
                    f" - {detail}" if detail else "",
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("account %s: could not check credentials: %s", account.name, exc)


def main() -> None:
    _configure_logging()
    _log_startup()
    mcp.run(transport="stdio")
