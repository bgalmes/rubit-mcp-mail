"""MIME handling: BODYSTRUCTURE walking, header decoding, body extraction.

Working from BODYSTRUCTURE rather than downloading whole messages means
`read_message` fetches only the text parts, so a mail with a 20 MB attachment
still costs a few kilobytes to read.
"""

from __future__ import annotations

import binascii
import email.header
import logging
import quopri
import re
from base64 import b64decode
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Attachment, EmailAddress

log = logging.getLogger(__name__)

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


def _children(node) -> list:
    """The child bodies of a multipart node.

    IMAPClient hands back a multipart as ``([child, ...], subtype, params, ...)``
    - the children nested in a single list at index 0. Reading that list as one
    child inserts a level of nesting the server does not have, so part ids come
    out one level too deep ('1.1' for what the server calls '1') and every
    BODY[...] fetch against them comes back NIL.
    """
    if node and isinstance(node[0], list):
        return list(node[0])
    # Hand-written plain tuples: body1, ..., bodyN, subtype, params, ...
    # The children run until the first string (the subtype); everything after
    # that is metadata, including param tuples that would look like children.
    children = []
    for entry in node:
        if isinstance(entry, (bytes, str)):
            break
        if isinstance(entry, (list, tuple)):
            children.append(entry)
    return children


def walk_bodystructure(node, prefix: str = "") -> list[Part]:
    """Flatten a BODYSTRUCTURE into leaf parts with RFC 3501 part ids."""
    parts: list[Part] = []

    if _is_multipart(node):
        for index, child in enumerate(_children(node), start=1):
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


def body_candidates(parts: list[Part]) -> list[tuple[Part, str]]:
    """Rank the parts worth showing as the body, best first.

    text/plain outranks text/html, but only as a preference: an HTML newsletter
    is routinely sent as multipart/alternative whose text/plain leg is an empty
    placeholder, so the caller fetches down this list until a part actually
    yields text rather than committing to the first one. Parts the server
    already reports as empty are dropped here, to save a pointless round trip.
    """
    text_parts = [p for p in parts if p.maintype == "text" and not p.is_attachment]
    usable = [p for p in text_parts if p.size != 0]
    ranked = [(p, "text") for p in usable if p.subtype == "plain"]
    ranked += [(p, "html-converted") for p in usable if p.subtype == "html"]
    # Any other text/* subtype (markdown, calendar) beats showing nothing.
    ranked += [(p, "text") for p in usable if p.subtype not in ("plain", "html")]
    return ranked


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
    except (binascii.Error, ValueError) as exc:
        # Malformed encoding: fall back to the raw bytes, but say so. Silently
        # returning mangled text is how an empty body becomes a mystery.
        log.warning(
            "part %s: could not undo %s encoding (%s); using the raw bytes",
            part.part_id, encoding, exc,
        )

    charset = part.params.get("charset") or "utf-8"
    try:
        return data.decode(charset, "replace")
    except LookupError:
        log.info("part %s: unknown charset %r; decoding as utf-8", part.part_id, charset)
        return data.decode("utf-8", "replace")


# Enough to keep a body readable when html2text itself fails on us.
_TAG = re.compile(r"<[^>]+>")
_DROPPED = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)


def _strip_tags(html: str) -> str:
    import html as html_module

    text = _DROPPED.sub(" ", html)
    return re.sub(r"\n{3,}", "\n\n", html_module.unescape(_TAG.sub(" ", text))).strip()


def html_to_text(html: str) -> str:
    import html2text

    converter = html2text.HTML2Text()
    converter.ignore_images = True
    converter.body_width = 0  # Never hard-wrap; it mangles quoted replies.
    # Off by default, which transliterates to ASCII and turns "Café" into "Cafe".
    converter.unicode_snob = True
    # Newsletters are laid out in nested tables. Rendered as Markdown tables they
    # come out as "---|---" rubble with adjacent paragraphs run onto one line;
    # treated as plain blocks the prose keeps its paragraph breaks.
    converter.ignore_tables = True
    # Reference-style links. A newsletter repeats the same long tracking URL on
    # every headline, and inline links put two thirds of the delivered characters
    # inside brackets; as references they are deduplicated and moved to the foot,
    # which halves the body without losing a single target.
    converter.inline_links = False
    try:
        return converter.handle(html).strip()
    except Exception:  # noqa: BLE001 - one hostile newsletter must not lose the body
        log.exception("html2text failed; falling back to stripping tags")
        return _strip_tags(html)


# Zero-width and non-breaking padding. Senders run these out in long ribbons to
# stretch the preview line a mail client shows next to the subject; they carry no
# text and can run to hundreds of characters in both the plain and HTML legs.
_INVISIBLE = "\u00a0\u200b\u200c\u200d\ufeff"
# A run means two or more, optionally separated by ordinary spaces or tabs - but
# never by a newline, or a match would swallow the blank line between paragraphs.
_SPACER_RUN = re.compile(f"[{_INVISIBLE}](?:[^\\S\\r\\n]*[{_INVISIBLE}])+")


def normalize_spacing(text: str) -> str:
    """Collapse padding ribbons, leaving a lone nbsp inside prose alone."""
    return re.sub(r"\n{3,}", "\n\n", _SPACER_RUN.sub(" ", text))


_TRUNCATED = "\n\n[...truncated...]"

# A reference definition html2text emits at the foot: "   [3]: https://..."
_REF_DEF = re.compile(r"^ *\[(\d+)\]: \S+")

# Most of a truncated body should still be the message, not its link list.
_REF_BUDGET_SHARE = 30


def _split_references(text: str) -> tuple[str, dict[str, str]]:
    """Separate the trailing reference-definition block from the prose."""
    lines = text.split("\n")
    start = len(lines)
    while start and (not lines[start - 1].strip() or _REF_DEF.match(lines[start - 1])):
        start -= 1
    block = lines[start:]
    if not any(_REF_DEF.match(line) for line in block):
        return text, {}
    refs = {}
    for line in block:
        if match := _REF_DEF.match(line):
            refs[match.group(1)] = line.strip()
    return "\n".join(lines[:start]).rstrip(), refs


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False

    prose, refs = _split_references(text)
    if not refs:
        return text[: max(max_chars - len(_TRUNCATED), 0)].rstrip() + _TRUNCATED, True

    # The definitions live at the foot, so a plain tail cut would leave every
    # "[7]" marker pointing at nothing. Reserve room for the ones still cited.
    reserve = max_chars * _REF_BUDGET_SHARE // 100
    kept = prose[: max(max_chars - len(_TRUNCATED) - reserve, 0)].rstrip()
    cited = sorted(
        (n for n in refs if re.search(rf"\[{n}\]", kept)), key=int
    )

    out = kept + _TRUNCATED
    tail = []
    for number in cited:
        line = refs[number]
        if len(out) + len("\n\n") + sum(len(t) + 1 for t in tail) + len(line) > max_chars:
            break
        tail.append(line)
    if tail:
        out += "\n\n" + "\n".join(tail)
    return out, True


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
