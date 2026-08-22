"""MIME handling: BODYSTRUCTURE walking, header decoding, body extraction.

Working from BODYSTRUCTURE rather than downloading whole messages means
`read_message` fetches only the text part, so a mail with a 20 MB attachment
still costs a few kilobytes to read.
"""

from __future__ import annotations

import binascii
import email.header
import quopri
from base64 import b64decode
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Attachment, EmailAddress

# Anything above this is almost certainly a runaway newsletter, not prose.
DEFAULT_MAX_CHARS = 20_000


@dataclass
class Part:
    """One leaf part of a message, addressable by its IMAP part id."""

    part_id: str
    maintype: str
    subtype: str
    params: dict[str, str] = field(default_factory=dict)
    encoding: str = ""
    size: int | None = None
    disposition: str = ""
    filename: str | None = None

    @property
    def content_type(self) -> str:
        return f"{self.maintype}/{self.subtype}"

    @property
    def is_attachment(self) -> bool:
        if self.disposition.lower() == "attachment":
            return True
        # Inline parts that carry a filename are still files worth listing.
        return bool(self.filename) and self.maintype != "text"


def _s(value) -> str:
    """IMAP returns bytes for most strings; normalize to str."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if value is None:
        return ""
    return str(value)


def _params(raw) -> dict[str, str]:
    """Turn the flat (key, value, key, value, ...) param list into a dict."""
    if not raw:
        return {}
    items = list(raw)
    return {
        _s(items[i]).lower(): _s(items[i + 1])
        for i in range(0, len(items) - 1, 2)
    }


def _is_multipart(node) -> bool:
    # IMAPClient marks these, but fall back to shape for plain tuples in tests.
    if getattr(node, "is_multipart", None) is not None:
        return bool(node.is_multipart)
    return bool(node) and isinstance(node[0], (list, tuple))


def walk_bodystructure(node, prefix: str = "") -> list[Part]:
    """Flatten a BODYSTRUCTURE into leaf parts with RFC 3501 part ids."""
    parts: list[Part] = []

    if _is_multipart(node):
        # Shape is: body1, body2, ..., bodyN, subtype, params, disposition, ...
        # The child bodies run until the first string (the subtype); everything
        # after that is metadata, including param tuples that would otherwise
        # be mistaken for children.
        children = []
        for entry in node:
            if isinstance(entry, (bytes, str)):
                break
            if isinstance(entry, (list, tuple)):
                children.append(entry)
        for index, child in enumerate(children, start=1):
            child_id = f"{prefix}{index}" if not prefix else f"{prefix}.{index}"
            parts.extend(walk_bodystructure(child, child_id))
        return parts

    # Leaf: (type, subtype, params, id, desc, encoding, size, ...)
    maintype = _s(node[0]).lower() if len(node) > 0 else "application"
    subtype = _s(node[1]).lower() if len(node) > 1 else "octet-stream"
    params = _params(node[2] if len(node) > 2 else None)
    encoding = _s(node[5]).lower() if len(node) > 5 else ""
    size = node[6] if len(node) > 6 and isinstance(node[6], int) else None

    # Disposition sits at a different index for text parts, which carry an
    # extra line-count field. Scan for it rather than hard-coding an offset.
    disposition = ""
    filename = params.get("name")
    for entry in node[7:]:
        if (
            isinstance(entry, (list, tuple))
            and entry
            and isinstance(entry[0], (bytes, str))
            and _s(entry[0]).lower() in ("attachment", "inline")
        ):
            disposition = _s(entry[0]).lower()
            disp_params = _params(entry[1] if len(entry) > 1 else None)
            filename = disp_params.get("filename") or filename
            break

    return [
        Part(
            part_id=prefix or "1",
            maintype=maintype,
            subtype=subtype,
            params=params,
            encoding=encoding,
            size=size,
            disposition=disposition,
            filename=decode_header(filename) if filename else None,
        )
    ]


def choose_body_part(parts: list[Part]) -> tuple[Part | None, str]:
    """Pick the part to show: prefer real text/plain, else html to convert."""
    candidates = [p for p in parts if p.maintype == "text" and not p.is_attachment]
    for part in candidates:
        if part.subtype == "plain":
            return part, "text"
    for part in candidates:
        if part.subtype == "html":
            return part, "html-converted"
    return None, "none"


def attachments_from(parts: list[Part]) -> list[Attachment]:
    return [
        Attachment(
            part_id=p.part_id,
            filename=p.filename,
            content_type=p.content_type,
            size=p.size,
        )
        for p in parts
        if p.is_attachment
    ]


def decode_body(raw: bytes, part: Part) -> str:
    """Undo the transfer encoding, then the charset."""
    data = raw
    encoding = (part.encoding or "").lower()
    try:
        if encoding == "base64":
            data = b64decode(raw, validate=False)
        elif encoding == "quoted-printable":
            data = quopri.decodestring(raw)
    except (binascii.Error, ValueError):
        pass  # Malformed encoding: fall back to the raw bytes.

    charset = part.params.get("charset") or "utf-8"
    try:
        return data.decode(charset, "replace")
    except LookupError:
        return data.decode("utf-8", "replace")


def html_to_text(html: str) -> str:
    import html2text

    converter = html2text.HTML2Text()
    converter.ignore_images = True
    converter.body_width = 0  # Never hard-wrap; it mangles quoted replies.
    return converter.handle(html).strip()


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "\n\n[...truncated...]", True


def decode_header(value) -> str:
    """Decode an RFC 2047 header such as '=?utf-8?B?...?='."""
    if value is None:
        return ""
    raw = _s(value)
    try:
        return str(email.header.make_header(email.header.decode_header(raw)))
    except (UnicodeDecodeError, ValueError, LookupError):
        return raw


def address_list(addresses) -> list[EmailAddress]:
    """Convert IMAPClient Address tuples into our model."""
    out: list[EmailAddress] = []
    for addr in addresses or ():
        mailbox, host = _s(addr.mailbox), _s(addr.host)
        out.append(
            EmailAddress(
                name=decode_header(addr.name) or None,
                email=f"{mailbox}@{host}" if mailbox and host else (mailbox or None),
            )
        )
    return out


def to_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        # IMAP dates are naive-but-UTC; make that explicit for JSON output.
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None
