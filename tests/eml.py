"""Turn a .eml fixture into what an IMAP server would answer for it.

Tests that hand-write BODYSTRUCTURE tuples can accidentally encode the same
assumptions as the parser under test. Deriving the structure from a real
message file instead keeps the fixtures honest: what goes into FakeIMAPClient
is the same thing an IMAP server computes from the MIME headers, and each
`BODY[<part id>]` is the part's payload still in its transfer encoding.
"""

from __future__ import annotations

import email
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

from imapclient.response_types import Address, Envelope

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Message:
    return email.message_from_bytes((FIXTURES / name).read_bytes())


def _flat_params(pairs) -> tuple | None:
    """Params come back over the wire as a flat (key, value, key, value) list."""
    out: list[bytes] = []
    for key, value in pairs:
        out += [key.upper().encode(), str(value).encode()]
    return tuple(out) or None


def _raw_payload(part: Message) -> bytes:
    """The payload as the server stores it: decoded from neither MIME nor charset."""
    payload = part.get_payload(decode=False)
    return payload.encode("utf-8", "surrogateescape") if isinstance(payload, str) else payload


def bodystructure(msg: Message, prefix: str = "") -> tuple:
    """Build the BODYSTRUCTURE tuple a server would report for this message."""
    if msg.is_multipart():
        children = [bodystructure(p) for p in msg.get_payload()]
        subtype = msg.get_content_subtype().upper().encode()
        params = _flat_params(
            [(k, v) for k, v in msg.get_params(failobj=[])[1:]]
        )
        # IMAPClient nests the children in a list at index 0; reproduce that
        # exactly, or these fixtures test a shape no server ever sends.
        return (children, subtype, params, None, None, None)

    maintype = msg.get_content_maintype().upper().encode()
    subtype = msg.get_content_subtype().upper().encode()
    params = _flat_params([(k, v) for k, v in msg.get_params(failobj=[])[1:]])
    encoding = (msg.get("content-transfer-encoding") or "7bit").upper().encode()
    raw = _raw_payload(msg)

    node: list = [maintype, subtype, params, None, None, encoding, len(raw)]
    if maintype == b"TEXT":
        # Text parts carry an extra line-count field before the extensions.
        node.append(raw.count(b"\n") + 1)
    disposition = None
    if msg.get_content_disposition():
        disposition = (
            msg.get_content_disposition().encode(),
            _flat_params(msg.get_params(failobj=[], header="content-disposition")[1:]),
        )
    node += [disposition, None, None]
    return tuple(node)


def part_bodies(msg: Message, prefix: str = "") -> dict[bytes, bytes]:
    """Map each leaf's `BODY[<part id>]` key to its still-encoded payload."""
    if msg.is_multipart():
        out: dict[bytes, bytes] = {}
        for index, child in enumerate(msg.get_payload(), start=1):
            child_id = f"{prefix}{index}" if not prefix else f"{prefix}.{index}"
            out |= part_bodies(child, child_id)
        return out
    return {f"BODY[{prefix or '1'}]".encode(): _raw_payload(msg)}


def _addresses(msg: Message, header: str):
    from email.utils import getaddresses

    raw = msg.get_all(header)
    if not raw:
        return None
    out = []
    for name, addr in getaddresses(raw):
        mailbox, _, host = addr.partition("@")
        out.append(
            Address(
                name=name.encode() if name else None,
                route=None,
                mailbox=mailbox.encode() or None,
                host=host.encode() or None,
            )
        )
    return tuple(out) or None


def envelope(msg: Message) -> Envelope:
    date = msg.get("date")
    parsed = parsedate_to_datetime(date) if date else datetime.now(timezone.utc)
    return Envelope(
        date=parsed,
        subject=(msg.get("subject") or "").encode(),
        from_=_addresses(msg, "from"),
        sender=None,
        reply_to=_addresses(msg, "reply-to"),
        to=_addresses(msg, "to"),
        cc=_addresses(msg, "cc"),
        bcc=None,
        in_reply_to=None,
        message_id=(msg.get("message-id") or "").encode() or None,
    )


def store_entry(name: str) -> dict:
    """The full FakeIMAPClient record for one .eml fixture."""
    msg = load(name)
    raw = (FIXTURES / name).read_bytes()
    entry = {
        b"ENVELOPE": envelope(msg),
        b"FLAGS": (),
        b"RFC822.SIZE": len(raw),
        b"INTERNALDATE": datetime(2026, 8, 21, 6, 2),
        b"BODYSTRUCTURE": bodystructure(msg),
    }
    entry.update(part_bodies(msg))
    return entry
