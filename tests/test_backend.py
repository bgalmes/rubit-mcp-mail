from datetime import datetime
from typing import cast

import pytest
from fake_imap import FakeIMAPClient

# IMAPClient returns Envelope/Address namedtuples; mimic just enough of them.
from imapclient import IMAPClient
from imapclient.response_types import Address, Envelope

from rubit_mcp_mail.auth.base import AuthStrategy
from rubit_mcp_mail.backends.imap import ImapBackend
from rubit_mcp_mail.config import Account
from rubit_mcp_mail.models import MessageHandle, StaleHandleError

TEXT_PART = (
    b"TEXT",
    b"PLAIN",
    (b"CHARSET", b"utf-8"),
    None,
    None,
    b"7BIT",
    20,
    1,
    None,
    None,
    None,
    None,
)
PDF_PART = (
    b"APPLICATION",
    b"PDF",
    (b"NAME", b"report.pdf"),
    None,
    None,
    b"BASE64",
    100,
    None,
    (b"attachment", (b"FILENAME", b"report.pdf")),
    None,
    None,
)
MIXED = (TEXT_PART, PDF_PART, b"MIXED", (b"BOUNDARY", b"b"), None, None, None)

FOLDERS = [
    ([rb"\HasNoChildren"], b"/", "INBOX"),
    ([rb"\HasNoChildren", rb"\Sent"], b"/", "Sent Items"),
    ([rb"\HasNoChildren", rb"\Junk"], b"/", "Junk Email"),
    ([rb"\Noselect", rb"\HasChildren"], b"/", "Containers"),
]


def envelope(subject, sender, msgid):
    # imapclient's Address/Envelope dataclasses declare these fields as plain
    # bytes, but the library itself hands back None for absent ones (see its
    # own Address docstring example) - the stubs just don't say so.
    return Envelope(
        date=datetime(2026, 8, 1, 9, 30),
        subject=subject.encode(),
        from_=(Address(name=b"Alice", route=None, mailbox=b"alice", host=b"example.com"),),  # type: ignore[arg-type]
        sender=None,
        reply_to=None,
        to=(Address(name=None, route=None, mailbox=b"me", host=b"outlook.com"),),  # type: ignore[arg-type]
        cc=None,
        bcc=None,
        in_reply_to=None,  # type: ignore[arg-type]
        message_id=msgid.encode(),  # type: ignore[arg-type]
    )


def make_backend(uidvalidity=1000):
    messages = {
        "INBOX": {
            uid: {
                b"ENVELOPE": envelope(f"Subject {uid}", "alice", f"<{uid}@example.com>"),
                b"FLAGS": (b"\\Seen",) if uid % 2 else (),
                b"RFC822.SIZE": 1000 + uid,
                b"INTERNALDATE": datetime(2026, 8, 1, 9, 30),
                b"BODYSTRUCTURE": MIXED if uid == 3 else TEXT_PART,
                b"BODY[1]": b"Hello from message %d" % uid,
                b"BODY[2]": b"cmVwb3J0IGJvZHk=",  # base64 "report body"
            }
            for uid in (1, 2, 3, 4, 5)
        },
        "Junk Email": {},
    }
    fake = FakeIMAPClient(FOLDERS, messages, uidvalidity=uidvalidity)
    account = Account(
        name="test", provider="generic", email="me@outlook.com", host="imap.test.invalid"
    )
    backend = ImapBackend(account, auth=cast(AuthStrategy, object()))
    backend._client = cast(IMAPClient, fake)  # skip the network
    return backend, fake


class TestFolders:
    def test_roles_and_noselect_filtering(self):
        backend, _ = make_backend()
        folders = backend.list_folders()
        assert [(f.role, f.name) for f in folders] == [
            ("inbox", "INBOX"),
            ("sent", "Sent Items"),
            ("junk", "Junk Email"),
        ]

    def test_resolve_by_role_and_raw_name(self):
        backend, _ = make_backend()
        assert backend.resolve_folder("junk") == "Junk Email"
        assert backend.resolve_folder("Junk Email") == "Junk Email"
        assert backend.resolve_folder("inbox") == "INBOX"
        assert backend.resolve_folder(None) == "INBOX"

    def test_unknown_folder_lists_alternatives(self):
        backend, _ = make_backend()
        with pytest.raises(ValueError, match="Available:"):
            backend.resolve_folder("nonexistent")


class TestListing:
    def test_newest_first_and_paginated(self):
        backend, _ = make_backend()
        page = backend.list_messages(limit=2)
        assert [m.subject for m in page] == ["Subject 5", "Subject 4"]
        page2 = backend.list_messages(limit=2, offset=2)
        assert [m.subject for m in page2] == ["Subject 3", "Subject 2"]

    def test_slices_before_fetching(self):
        """The whole point of paging: a huge folder must not be fetched wholesale."""
        backend, fake = make_backend()
        backend.list_messages(limit=2)
        fetches = [c for c in fake.calls if c[0] == "fetch"]
        assert len(fetches) == 1
        assert fetches[0][1] == (5, 4)

    def test_summary_fields(self):
        backend, _ = make_backend()
        msg = backend.list_messages(limit=1)[0]
        assert msg.subject == "Subject 5"
        assert str(msg.from_[0]) == "Alice <alice@example.com>"
        assert msg.seen is True
        assert msg.size == 1005
        assert msg.message_id == "<5@example.com>"
        assert msg.has_attachments is False

    def test_has_attachments_flag(self):
        backend, _ = make_backend()
        by_subject = {m.subject: m for m in backend.list_messages(limit=10)}
        assert by_subject["Subject 3"].has_attachments is True
        assert by_subject["Subject 2"].has_attachments is False

    def test_listing_never_downloads_bodies(self):
        backend, fake = make_backend()
        backend.list_messages(limit=5)
        for call in fake.calls:
            if call[0] == "fetch":
                assert not any("BODY[" in k or "RFC822]" in k for k in call[2])


class TestReadOnly:
    def test_always_examines(self):
        backend, fake = make_backend()
        backend.list_messages(limit=1)
        selects = [c for c in fake.calls if c[0] == "select_folder"]
        assert selects and all(c[2] is True for c in selects)

    def test_body_fetch_uses_peek(self):
        """FakeIMAPClient raises on a non-PEEK body fetch, which would set \\Seen."""
        backend, fake = make_backend()
        handle = backend.list_messages(limit=5)[0].handle
        backend.read_message(handle)
        # BODYSTRUCTURE is metadata; only indexed BODY[...] fetches set \Seen.
        body_fetches = [
            k
            for c in fake.calls
            if c[0] == "fetch"
            for k in c[2]
            if k.startswith("BODY[") or k.startswith("BODY.PEEK[")
        ]
        assert body_fetches and all(k.startswith("BODY.PEEK[") for k in body_fetches)

    def test_no_mutating_commands_exist(self):
        """Guard against a future edit calling a mutating IMAP command."""
        import inspect
        import re

        from rubit_mcp_mail.backends import imap

        source = inspect.getsource(imap)
        forbidden = (
            "add_flags",
            "remove_flags",
            "set_flags",
            "delete_messages",
            "expunge",
            "copy",
            "move",
            "append",
            "create_folder",
            "delete_folder",
            "rename_folder",
        )
        # Only calls on the IMAP client count; `criteria.append(...)` is a list op.
        called = set(re.findall(r"client\.(\w+)\s*\(", source))
        assert not called & set(forbidden), f"mutating IMAP calls: {called & set(forbidden)}"


class TestReading:
    def test_reads_body_and_attachments(self):
        backend, _ = make_backend()
        handle = {m.subject: m.handle for m in backend.list_messages(limit=5)}["Subject 3"]
        msg = backend.read_message(handle)
        assert msg.body == "Hello from message 3"
        assert msg.body_format == "text"
        assert msg.truncated is False
        assert [a.filename for a in msg.attachments] == ["report.pdf"]

    def test_truncation(self):
        backend, fake = make_backend()
        fake._messages["INBOX"][5][b"BODY[1]"] = b"x" * 5000
        handle = backend.list_messages(limit=1)[0].handle
        msg = backend.read_message(handle, max_chars=100)
        assert msg.truncated is True
        assert "[...truncated...]" in msg.body

    def test_attachment_is_transfer_decoded(self):
        backend, _ = make_backend()
        handle = {m.subject: m.handle for m in backend.list_messages(limit=5)}["Subject 3"]
        filename, data = backend.fetch_attachment(handle, "2")
        assert filename == "report.pdf"
        assert data == b"report body"

    def test_unknown_part_id_lists_available(self):
        backend, _ = make_backend()
        handle = {m.subject: m.handle for m in backend.list_messages(limit=5)}["Subject 3"]
        with pytest.raises(ValueError, match="Attachments: 2"):
            backend.fetch_attachment(handle, "99")


class TestHandles:
    def test_roundtrip_with_awkward_folder_name(self):
        h = MessageHandle(account="a", folder="[Gmail]/All Mail", uidvalidity=7, uid=42)
        assert MessageHandle.decode(h.encode()) == h

    def test_malformed_handle(self):
        with pytest.raises(ValueError, match="Not a valid message handle"):
            MessageHandle.decode("garbage!!")

    def test_stale_handle_detected(self):
        """A renumbered folder must error, not silently read the wrong message."""
        backend, _ = make_backend()
        handle = backend.list_messages(limit=1)[0].handle
        backend2, fake2 = make_backend(uidvalidity=2000)  # folder renumbered
        with pytest.raises(StaleHandleError, match="UIDVALIDITY"):
            backend2.read_message(handle)

    def test_handle_from_another_account_rejected(self):
        backend, _ = make_backend()
        other = MessageHandle(
            account="somewhere-else", folder="INBOX", uidvalidity=1000, uid=1
        ).encode()
        with pytest.raises(ValueError, match="belongs to account"):
            backend.read_message(other)
