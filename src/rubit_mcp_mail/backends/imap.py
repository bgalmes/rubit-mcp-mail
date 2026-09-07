"""Mostly-read-only IMAP backend.

Read-only is enforced in two places, both of which matter:
  * every folder is opened with readonly=True, which issues EXAMINE not SELECT;
  * every body fetch uses BODY.PEEK[...], never BODY[...], which would set \\Seen
    as a side effect of reading.

The two deliberate exceptions are `mark_read` (STORE +\\Seen) and
`move_message` (MOVE, or IMAPClient's COPY+STORE\\Deleted+EXPUNGE emulation on
servers without RFC 6851). Both SELECT their folder with readonly=False - the
only place in this module that happens - and are gated at the tool layer by
Account.can_write, off by default. No other mutating IMAP command is used
anywhere in this module.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date
from typing import cast

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientAbortError, IMAPClientError
from imapclient.response_types import Envelope

from ..auth.base import AuthStrategy
from ..config import Account
from ..mime import (
    DEFAULT_MAX_CHARS,
    address_list,
    attachments_from,
    body_candidates,
    decode_body,
    decode_header,
    html_to_text,
    normalize_spacing,
    to_datetime,
    truncate,
    walk_bodystructure,
)
from ..models import (
    BodyFormat,
    Folder,
    FolderRole,
    Message,
    MessageHandle,
    MessageSummary,
    StaleHandleError,
)

log = logging.getLogger(__name__)

# RFC 6154 SPECIAL-USE flags -> our normalized roles.
SPECIAL_USE = {
    rb"\inbox": "inbox",
    rb"\sent": "sent",
    rb"\drafts": "drafts",
    rb"\junk": "junk",
    rb"\trash": "trash",
    rb"\archive": "archive",
    rb"\all": "archive",
}

# Fallback for servers that do not advertise SPECIAL-USE - which includes
# Outlook.com, so this is the normal path there, not an edge case. Names are
# matched accent-insensitively against the localizations Outlook actually ships,
# because a Spanish mailbox calls its sent folder "Elementos enviados".
# INBOX is exempt: it is always literally "INBOX" on the wire, in every locale.
NAME_PATTERNS: list[tuple[str, FolderRole]] = [
    (
        r"^inbox$|bandeja de entrada|safata d.entrada|boite de reception|"
        r"posteingang|caixa de entrada|posta in arrivo",
        "inbox",
    ),
    (r"sent|enviad|enviat|envoy|gesendete|inviata|itens enviados", "sent"),
    (r"draft|borrador|esborrany|brouillon|entwurf|entwurfe|bozze|rascunho", "drafts"),
    (
        r"junk|spam|bulk|no deseado|brossa|indesirable|indesiderata|lixo|"
        r"unerwunscht",
        "junk",
    ),
    (
        r"trash|deleted|elimin|suprimit|supprim|gelosch|papierkorb|papelera|"
        r"excluid|cestino|bin$",
        "trash",
    ),
    (r"archive|archivo|arxiu|archiv|arquivo|archivio|all mail", "archive"),
]


def _fold(text: str) -> str:
    """Lowercase and strip accents so "Éléments supprimés" matches "supprim"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _has_flag(flags, wanted: str) -> bool:
    for flag in flags or ():
        raw = flag.decode("ascii", "replace") if isinstance(flag, bytes) else str(flag)
        if raw.lstrip("\\").lower() == wanted.lower():
            return True
    return False


def folder_role(flags, name: str) -> FolderRole:
    """Normalize a folder to a role, preferring the server's own declaration."""
    for flag in flags or ():
        raw = flag if isinstance(flag, bytes) else str(flag).encode()
        if role := SPECIAL_USE.get(raw.lower()):
            return role  # type: ignore[return-value]

    # Match on the leaf name so "[Gmail]/Sent Mail" and "INBOX/Sent" both work.
    leaf = _fold(re.split(r"[/.]", name)[-1].strip())
    if leaf == "inbox" or _fold(name.strip()) == "inbox":
        return "inbox"
    for pattern, role in NAME_PATTERNS:
        if re.search(pattern, leaf):
            return role
    return "other"


def build_search_criteria(
    text: str | None = None,
    from_: str | None = None,
    subject: str | None = None,
    since: date | None = None,
    before: date | None = None,
    unread_only: bool = False,
) -> list:
    """Build IMAP SEARCH criteria as a list.

    Passing a list (rather than concatenating a string) keeps IMAPClient in
    charge of quoting, so a subject containing quotes or CRLF cannot inject
    additional IMAP commands.
    """
    criteria: list = []
    if unread_only:
        criteria.append("UNSEEN")
    if from_:
        criteria += ["FROM", from_]
    if subject:
        criteria += ["SUBJECT", subject]
    if text:
        criteria += ["TEXT", text]
    if since:
        criteria += ["SINCE", since]
    if before:
        criteria += ["BEFORE", before]
    return criteria or ["ALL"]


def _needs_utf8(criteria: list) -> bool:
    return any(isinstance(item, str) and not item.isascii() for item in criteria)


class ImapBackend:
    def __init__(self, account: Account, auth: AuthStrategy) -> None:
        self._account = account
        self._auth = auth
        self._client: IMAPClient | None = None
        self._selected: str | None = None
        self._folders: list[tuple[list, str]] | None = None

    # -- connection ------------------------------------------------------
    def _connect(self) -> IMAPClient:
        profile = self._account.profile
        if profile.host is None:
            raise ValueError(f"Account {self._account.name!r} has no host configured.")
        log.debug("connecting to %s:%s", profile.host, profile.port)
        try:
            client = IMAPClient(profile.host, port=profile.port, ssl=profile.ssl)
        except (OSError, EOFError) as exc:
            # Bare socket errors ("Name or service not known") give no clue which
            # server was unreachable, which is unhelpful in a tool result.
            raise ConnectionError(
                f"Could not reach {profile.host}:{profile.port} for account "
                f"{self._account.name!r}: {exc}"
            ) from exc
        self._auth.login(client)
        self._selected = None
        return client

    @property
    def client(self) -> IMAPClient:
        if self._client is None:
            self._client = self._connect()
        return self._client

    def _retry(self, fn, *args, **kwargs):
        """Run fn, reconnecting once if the server dropped an idle connection."""
        try:
            return fn(*args, **kwargs)
        except (IMAPClientAbortError, OSError, EOFError) as exc:
            log.info("IMAP connection lost (%s); reconnecting", exc)
            self.close()
            self._client = self._connect()
            return fn(*args, **kwargs)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except Exception:  # noqa: BLE001 - closing a dead socket is not an error
                pass
        self._client = None
        self._selected = None
        self._folders = None

    def capabilities(self) -> list[str]:
        return [c.decode() if isinstance(c, bytes) else str(c) for c in self.client.capabilities()]

    # -- folders ---------------------------------------------------------
    def _raw_folders(self) -> list[tuple[list, str]]:
        if self._folders is None:
            listing = self._retry(self.client.list_folders)
            self._folders = [
                (flags, name if isinstance(name, str) else name.decode("utf-8", "replace"))
                for flags, _delim, name in listing
                # \Noselect entries are containers, not selectable mailboxes.
                if not _has_flag(flags, "noselect")
            ]
        return self._folders

    def list_folders(self) -> list[Folder]:
        out: list[Folder] = []
        for flags, name in self._raw_folders():
            role = folder_role(flags, name)
            messages = unseen = None
            try:
                status = self._retry(self.client.folder_status, name, [b"MESSAGES", b"UNSEEN"])
                messages = status.get(b"MESSAGES")
                unseen = status.get(b"UNSEEN")
            except IMAPClientError:
                pass  # A folder we cannot STATUS is still worth listing.
            out.append(Folder(name=name, role=role, messages=messages, unseen=unseen))
        # Inbox first, then the other well-known roles, then everything else.
        order = ["inbox", "archive", "sent", "drafts", "junk", "trash", "other"]
        out.sort(key=lambda f: (order.index(f.role), f.name.lower()))
        return out

    def resolve_folder(self, folder: str | None) -> str:
        """Accept either a normalized role ('junk') or a raw name ('Junk Email')."""
        wanted = (folder or "inbox").strip()
        for _flags, name in self._raw_folders():
            if name.lower() == wanted.lower():
                return name
        matches = [
            name
            for flags, name in self._raw_folders()
            if folder_role(flags, name) == wanted.lower()
        ]
        if matches:
            return matches[0]
        known = ", ".join(sorted(n for _f, n in self._raw_folders()))
        raise ValueError(f"No folder matching {folder!r}. Available: {known}")

    def _select(self, folder: str, readonly: bool = True) -> int:
        """Open the folder and return its UIDVALIDITY.

        EXAMINE (readonly=True, the default) for every read path; SELECT
        (readonly=False) only for mark_read/move_message, the sole
        intentional mutations in this module.
        """
        name = self.resolve_folder(folder)
        info = self._retry(self.client.select_folder, name, readonly=readonly)
        self._selected = name
        return int(info.get(b"UIDVALIDITY", 0))

    # -- listing ---------------------------------------------------------
    def _summaries(self, name: str, uidvalidity: int, uids: list[int]) -> list[MessageSummary]:
        if not uids:
            return []
        fetched = self._retry(
            self.client.fetch,
            uids,
            [b"ENVELOPE", b"FLAGS", b"RFC822.SIZE", b"INTERNALDATE", b"BODYSTRUCTURE"],
        )
        out: list[MessageSummary] = []
        for uid in uids:  # preserve our newest-first ordering
            data = fetched.get(uid)
            if not data:
                continue
            out.append(self._summary(name, uidvalidity, uid, data))
        return out

    def _summary(self, name: str, uidvalidity: int, uid: int, data: dict) -> MessageSummary:
        env = data.get(b"ENVELOPE")
        flags = {f.lower() for f in (data.get(b"FLAGS") or ())}
        parts = []
        if bs := data.get(b"BODYSTRUCTURE"):
            try:
                parts = walk_bodystructure(bs)
            except Exception:  # noqa: BLE001 - odd structures must not break listing
                log.debug("could not parse BODYSTRUCTURE for uid %s", uid)
        handle = MessageHandle(
            account=self._account.name, folder=name, uidvalidity=uidvalidity, uid=uid
        )
        # MessageSummary.from_ is aliased to "from" (a Python keyword), so pyright's
        # synthesized __init__ only accepts the alias as a keyword; go through a
        # dict to populate the field by its real name instead.
        fields = {
            "handle": handle.encode(),
            "subject": decode_header(env.subject) if env and env.subject else None,
            "from_": address_list(env.from_) if env else [],
            "to": address_list(env.to) if env else [],
            "date": to_datetime(env.date) if env else to_datetime(data.get(b"INTERNALDATE")),
            "seen": b"\\seen" in flags,
            "flagged": b"\\flagged" in flags,
            "answered": b"\\answered" in flags,
            "has_attachments": any(p.is_attachment for p in parts),
            "size": data.get(b"RFC822.SIZE"),
            "message_id": decode_header(env.message_id) if env and env.message_id else None,
        }
        return MessageSummary(**fields)

    def _page(self, folder: str, criteria: list, limit: int, offset: int) -> list[MessageSummary]:
        uidvalidity = self._select(folder)
        name = self._selected or folder
        charset = "UTF-8" if _needs_utf8(criteria) else None
        try:
            uids = self._retry(self.client.search, criteria, charset)
        except IMAPClientError as exc:
            # Some servers reject an explicit charset; retry without it.
            if charset is None:
                raise
            log.debug("search with charset failed (%s); retrying without", exc)
            uids = self._retry(self.client.search, criteria, None)
        # Newest first, and slice before fetching so a huge mailbox stays cheap.
        uids = sorted(uids, reverse=True)[offset : offset + limit]
        return self._summaries(name, uidvalidity, list(uids))

    def list_messages(
        self,
        folder: str = "inbox",
        limit: int = 25,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[MessageSummary]:
        criteria = build_search_criteria(unread_only=unread_only)
        return self._page(folder, criteria, limit, offset)

    def search_messages(
        self,
        folder: str = "inbox",
        text: str | None = None,
        from_: str | None = None,
        subject: str | None = None,
        since: date | None = None,
        before: date | None = None,
        unread_only: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[MessageSummary]:
        criteria = build_search_criteria(
            text=text,
            from_=from_,
            subject=subject,
            since=since,
            before=before,
            unread_only=unread_only,
        )
        return self._page(folder, criteria, limit, offset)

    # -- reading ---------------------------------------------------------
    def _open_handle(self, handle: str, readonly: bool = True) -> MessageHandle:
        parsed = MessageHandle.decode(handle)
        if parsed.account != self._account.name:
            raise ValueError(
                f"Handle belongs to account {parsed.account!r}, not {self._account.name!r}."
            )
        current = self._select(parsed.folder, readonly=readonly)
        if current != parsed.uidvalidity:
            raise StaleHandleError(
                f"Folder {parsed.folder!r} was renumbered since this handle was issued "
                "(UIDVALIDITY changed). Re-run the search or listing to get fresh handles."
            )
        return parsed

    def _body_text(self, uid: int, part, body_format: BodyFormat) -> str:
        """Fetch one candidate part and render it, or "" if it holds no text."""
        # PEEK so that reading a message never marks it as read.
        key = f"BODY.PEEK[{part.part_id}]".encode()
        fetched = self._retry(self.client.fetch, [uid], [key]).get(uid, {})
        raw = cast(bytes, fetched.get(f"BODY[{part.part_id}]".encode()) or b"")
        if not raw:
            log.debug("uid %s: server returned no data for part %s", uid, part.part_id)
            return ""
        text = decode_body(raw, part)
        if body_format == "html-converted":
            text = html_to_text(text)
        # Both legs carry the sender's preview-line padding, so strip it here
        # rather than only on the path that happens to go through html2text.
        return normalize_spacing(text).strip()

    def read_message(self, handle: str, max_chars: int = DEFAULT_MAX_CHARS) -> Message:
        parsed = self._open_handle(handle)
        uid = parsed.uid
        meta = self._retry(
            self.client.fetch,
            [uid],
            [b"ENVELOPE", b"FLAGS", b"RFC822.SIZE", b"INTERNALDATE", b"BODYSTRUCTURE"],
        ).get(uid)
        if not meta:
            raise ValueError("Message no longer exists in that folder.")

        summary = self._summary(parsed.folder, parsed.uidvalidity, uid, meta)
        env = cast("Envelope | None", meta.get(b"ENVELOPE"))
        parts = walk_bodystructure(meta[b"BODYSTRUCTURE"]) if meta.get(b"BODYSTRUCTURE") else []
        candidates = body_candidates(parts)

        body = ""
        # If every candidate turns out to be empty, still report what the message
        # claimed to be rather than "none", which means "no text part at all".
        body_format = candidates[0][1] if candidates else "none"

        for part, fmt in candidates:
            text = self._body_text(uid, part, fmt)
            if not text:
                # An HTML newsletter's text/plain leg is sometimes a blank
                # placeholder; keep going rather than reporting it as empty.
                log.debug(
                    "uid %s: body part %s (%s) is empty", uid, part.part_id, part.content_type
                )
                continue
            body, body_format = text, fmt
            break
        else:
            if candidates:
                log.warning(
                    "uid %s: every text part is empty (%s); returning an empty body",
                    uid,
                    ", ".join(f"{p.part_id} {p.content_type}" for p, _ in candidates),
                )

        body, truncated = truncate(body, max_chars)

        return Message(
            **summary.model_dump(by_alias=True),
            cc=address_list(env.cc) if env else [],
            reply_to=address_list(env.reply_to) if env else [],
            body=body,
            body_format=body_format,
            truncated=truncated,
            attachments=attachments_from(parts),
        )

    def fetch_attachment(self, handle: str, part_id: str) -> tuple[str, bytes]:
        parsed = self._open_handle(handle)
        uid = parsed.uid
        meta = self._retry(self.client.fetch, [uid], [b"BODYSTRUCTURE"]).get(uid)
        if not meta:
            raise ValueError("Message no longer exists in that folder.")
        parts = walk_bodystructure(meta[b"BODYSTRUCTURE"])
        match = next((p for p in parts if p.part_id == part_id), None)
        if match is None:
            available = ", ".join(p.part_id for p in parts if p.is_attachment) or "none"
            raise ValueError(f"No part {part_id!r} in this message. Attachments: {available}")

        key = f"BODY.PEEK[{part_id}]".encode()
        fetched = self._retry(self.client.fetch, [uid], [key]).get(uid, {})
        raw = cast(bytes, fetched.get(f"BODY[{part_id}]".encode()) or b"")

        import binascii
        import quopri
        from base64 import b64decode

        encoding = (match.encoding or "").lower()
        try:
            if encoding == "base64":
                raw = b64decode(raw, validate=False)
            elif encoding == "quoted-printable":
                raw = quopri.decodestring(raw)
        except (binascii.Error, ValueError):
            pass

        filename = match.filename or f"part-{part_id}"
        return filename, raw

    # -- writing (gated by Account.can_write, off by default) ------------
    def mark_read(self, handle: str) -> None:
        parsed = self._open_handle(handle, readonly=False)
        self._retry(self.client.add_flags, [parsed.uid], [b"\\Seen"])

    def move_message(self, handle: str, folder: str) -> str:
        """Move the message to `folder`, returning the destination's name.

        The message's UID (and possibly UIDVALIDITY) in the destination is
        not reported back - relying on UIDPLUS/COPYUID responses is not
        portable across servers - so the caller's handle is stale afterwards;
        a fresh list/search against the destination folder is needed to get
        one that points at the moved message.
        """
        parsed = self._open_handle(handle, readonly=False)
        dest = self.resolve_folder(folder)
        self._retry(self.client.move, [parsed.uid], dest)
        return dest
