"""Regression tests for empty message bodies.

Every multipart message used to come back with body "". `walk_bodystructure`
read IMAPClient's nested child list as an extra level of nesting, so it asked
for BODY[1.1] where the server had part 1; the fetch returned NIL and every
candidate looked empty. See tests/test_mime.py for the part-id tests.

A separate, real case is covered here: an HTML newsletter whose text/plain leg
genuinely holds nothing, where the body has to come from the text/html leg.

The fixtures are real .eml files, converted to server responses by eml.py in
IMAPClient's own shape, so these tests exercise the path production does.
"""

from __future__ import annotations

import logging

import pytest

from eml import store_entry
from fake_imap import FakeIMAPClient
from rubit_mcp_mail.backends.imap import ImapBackend
from rubit_mcp_mail.config import Account
from rubit_mcp_mail.mime import (
    body_candidates,
    html_to_text,
    walk_bodystructure,
)

FOLDERS = [([rb"\HasNoChildren"], b"/", "INBOX")]


def backend_for(*fixtures: str):
    messages = {"INBOX": {i: store_entry(name) for i, name in enumerate(fixtures, start=1)}}
    fake = FakeIMAPClient(FOLDERS, messages)
    account = Account(name="test", provider="generic", email="me@outlook.com",
                      host="imap.test.invalid")
    backend = ImapBackend(account, auth=object())
    backend._client = fake
    return backend, fake


def read(fixture: str, **kwargs):
    backend, fake = backend_for(fixture)
    handle = backend.list_messages(limit=1)[0].handle
    return backend.read_message(handle, **kwargs), fake


class TestHtmlOnlyNewsletters:
    def test_empty_plain_part_falls_back_to_html(self):
        """The bug: an empty text/plain leg used to win and produce body ""."""
        msg, _ = read("html_only_newsletter.eml")
        assert msg.body_format == "html-converted"
        assert "Anthropic ships a new model" in msg.body
        assert msg.body.startswith("# TLDR")

    def test_whitespace_only_plain_part_falls_back_to_html(self):
        """A placeholder with real bytes on the wire only shows up after decoding."""
        msg, _ = read("plain_placeholder.eml")
        assert msg.body_format == "html-converted"
        assert "the real body lives here" in msg.body
        # The html leg declares iso-8859-1; its entity must survive conversion.
        assert "Café news" in msg.body

    def test_nested_alternative_inside_mixed(self):
        """multipart/mixed > multipart/alternative > text/html must be descended."""
        msg, _ = read("html_only_with_attachment.eml")
        assert msg.body_format == "html-converted"
        assert "Issue 712, curated by Rahul." in msg.body
        assert [a.filename for a in msg.attachments] == ["sponsor.pdf"]

    def test_metadata_still_parsed(self):
        """Guard the symptom that made the bug confusing: headers were always fine."""
        msg, _ = read("html_only_newsletter.eml")
        assert msg.subject == "TLDR 2026-08-21"
        assert str(msg.from_[0]) == "TLDR <dan@tldrnewsletter.com>"
        assert msg.message_id == "<newsletter-2026-08-21@tldrnewsletter.com>"

    def test_reading_still_only_peeks(self):
        """The fallback adds a fetch; it must not be the kind that sets \\Seen."""
        _, fake = read("plain_placeholder.eml")
        body_fetches = [
            k for c in fake.calls if c[0] == "fetch" for k in c[2]
            if k.startswith("BODY[") or k.startswith("BODY.PEEK[")
        ]
        # Both legs get read: the empty plain one, then the html fallback.
        assert body_fetches == ["BODY.PEEK[1]", "BODY.PEEK[2]"]

    def test_empty_part_is_not_fetched_at_all(self):
        """The server already told us part 1 is 0 bytes; don't spend a round trip."""
        _, fake = read("html_only_newsletter.eml")
        fetched_parts = [
            k for c in fake.calls if c[0] == "fetch" for k in c[2] if "BODY.PEEK[" in k
        ]
        assert fetched_parts == ["BODY.PEEK[2]"]


class TestTruncationAfterFallback:
    def test_converted_html_still_truncates(self):
        msg, _ = read("html_only_newsletter.eml", max_chars=50)
        assert msg.truncated is True
        assert msg.body.endswith("[...truncated...]")
        assert len(msg.body) < 100

    def test_untruncated_when_it_fits(self):
        msg, _ = read("html_only_newsletter.eml", max_chars=20_000)
        assert msg.truncated is False
        assert "[...truncated...]" not in msg.body

    def test_boundary_is_the_converted_length(self):
        """max_chars applies to what the caller receives, not the raw HTML."""
        full, _ = read("html_only_newsletter.eml", max_chars=0)
        exact, _ = read("html_only_newsletter.eml", max_chars=len(full.body))
        assert exact.truncated is False and exact.body == full.body
        cut, _ = read("html_only_newsletter.eml", max_chars=len(full.body) - 1)
        assert cut.truncated is True


class TestCandidateRanking:
    def test_zero_sized_plain_is_dropped(self):
        parts = walk_bodystructure(store_entry("html_only_newsletter.eml")[b"BODYSTRUCTURE"])
        assert [(p.part_id, fmt) for p, fmt in body_candidates(parts)] == [
            ("2", "html-converted")
        ]

    def test_plain_still_outranks_html_when_it_has_content(self):
        parts = walk_bodystructure(store_entry("plain_placeholder.eml")[b"BODYSTRUCTURE"])
        assert [(p.part_id, fmt) for p, fmt in body_candidates(parts)] == [
            ("1", "text"),
            ("2", "html-converted"),
        ]


class TestTerseReplies:
    def test_short_genuine_message_keeps_its_plain_leg(self):
        """A short real mail is the message, not a stub standing in for one."""
        msg, _ = read("terse_reply.eml")
        assert msg.body_format == "text"
        assert msg.body == "Mira esto: https://example.com/menu\n\nQue te parece?"



class TestAttachmentPartIds:
    """Attachments were broken by the same wrong part ids as the body."""

    def test_attachment_reports_the_servers_part_id(self):
        msg, _ = read("html_only_with_attachment.eml")
        assert [(a.part_id, a.filename) for a in msg.attachments] == [("2", "sponsor.pdf")]

    def test_attachment_can_actually_be_fetched(self):
        """The id in the listing has to be the id the server answers to."""
        backend, _ = backend_for("html_only_with_attachment.eml")
        handle = backend.list_messages(limit=1)[0].handle
        part_id = backend.read_message(handle).attachments[0].part_id
        filename, data = backend.fetch_attachment(handle, part_id)
        assert filename == "sponsor.pdf"
        assert data.startswith(b"%PDF-1.4")


class TestFailuresAreLogged:
    def test_all_parts_empty_is_logged_not_silent(self, caplog):
        backend, fake = backend_for("plain_placeholder.eml")
        # Blank out the html leg too, so nothing anywhere yields text.
        fake._messages["INBOX"][1][b"BODY[2]"] = b"<html><body></body></html>"
        handle = backend.list_messages(limit=1)[0].handle
        with caplog.at_level(logging.WARNING):
            msg = backend.read_message(handle)
        assert msg.body == ""
        assert "every text part is empty" in caplog.text

    def test_html_conversion_failure_is_logged_and_degrades(self, caplog, monkeypatch):
        """A converter blowing up must log and still return text, never ""."""
        import html2text

        def explode(self, html):
            raise RuntimeError("converter blew up")

        monkeypatch.setattr(html2text.HTML2Text, "handle", explode)
        with caplog.at_level(logging.ERROR):
            text = html_to_text("<p>real &amp; readable content</p>")
        assert "real & readable content" in text
        assert "html2text failed" in caplog.text
        assert "converter blew up" in caplog.text

    def test_clean_decode_logs_nothing(self, caplog):
        from rubit_mcp_mail.mime import decode_body

        part = walk_bodystructure(
            (b"TEXT", b"PLAIN", (b"CHARSET", b"utf-8"), None, None, b"QUOTED-PRINTABLE",
             5, 1, None, None, None, None)
        )[0]
        with caplog.at_level(logging.INFO):
            assert decode_body(b"caf=C3=A9", part) == "café"
        assert caplog.text == ""

    def test_unknown_charset_is_logged(self, caplog):
        from rubit_mcp_mail.mime import decode_body

        part = walk_bodystructure(
            (b"TEXT", b"PLAIN", (b"CHARSET", b"x-nonsense"), None, None, b"7BIT",
             2, 1, None, None, None, None)
        )[0]
        with caplog.at_level(logging.INFO):
            assert decode_body(b"hi", part) == "hi"
        assert "unknown charset" in caplog.text


@pytest.mark.parametrize(
    "fixture", ["html_only_newsletter.eml", "plain_placeholder.eml",
                "html_only_with_attachment.eml", "terse_reply.eml"]
)
def test_no_fixture_reads_back_empty(fixture):
    """The blanket invariant the bug violated."""
    msg, _ = read(fixture)
    assert msg.body.strip(), f"{fixture} came back with an empty body"
    assert msg.body_format != "none"
