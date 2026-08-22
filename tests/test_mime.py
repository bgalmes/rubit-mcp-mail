from rubit_mcp_mail.mime import (
    attachments_from,
    choose_body_part,
    decode_body,
    truncate,
    walk_bodystructure,
    decode_header,
)

TEXT_PART = (b"TEXT", b"PLAIN", (b"CHARSET", b"utf-8"), None, None, b"7BIT", 100, 5,
             None, None, None, None)
HTML_PART = (b"TEXT", b"HTML", (b"CHARSET", b"utf-8"), None, None, b"QUOTED-PRINTABLE",
             300, 10, None, None, None, None)
PDF_PART = (b"APPLICATION", b"PDF", (b"NAME", b"report.pdf"), None, None, b"BASE64",
            40000, None, (b"attachment", (b"FILENAME", b"report.pdf")), None, None)

ALTERNATIVE = (TEXT_PART, HTML_PART, b"ALTERNATIVE", (b"BOUNDARY", b"x1"), None, None, None)
MIXED = (ALTERNATIVE, PDF_PART, b"MIXED", (b"BOUNDARY", b"x0"), None, None, None)


class TestWalk:
    def test_nested_part_ids(self):
        parts = walk_bodystructure(MIXED)
        assert [(p.part_id, p.content_type) for p in parts] == [
            ("1.1", "text/plain"),
            ("1.2", "text/html"),
            ("2", "application/pdf"),
        ]

    def test_param_tuples_are_not_mistaken_for_children(self):
        """The (BOUNDARY, x) trailer must not be walked as a body part."""
        assert len(walk_bodystructure(MIXED)) == 3

    def test_single_part_message_is_part_1(self):
        parts = walk_bodystructure(TEXT_PART)
        assert [p.part_id for p in parts] == ["1"]

    def test_attachment_detection(self):
        parts = walk_bodystructure(MIXED)
        assert [p.is_attachment for p in parts] == [False, False, True]
        attachments = attachments_from(parts)
        assert len(attachments) == 1
        assert attachments[0].filename == "report.pdf"
        assert attachments[0].part_id == "2"
        assert attachments[0].size == 40000


class TestBodySelection:
    def test_prefers_plain_over_html(self):
        part, kind = choose_body_part(walk_bodystructure(MIXED))
        assert (part.part_id, kind) == ("1.1", "text")

    def test_falls_back_to_html(self):
        html_only = (HTML_PART, b"ALTERNATIVE", (b"BOUNDARY", b"b"), None, None, None)
        part, kind = choose_body_part(walk_bodystructure(html_only))
        assert (part.part_id, kind) == ("1", "html-converted")

    def test_no_text_part_at_all(self):
        only_pdf = (PDF_PART, b"MIXED", (b"BOUNDARY", b"b"), None, None, None)
        part, kind = choose_body_part(walk_bodystructure(only_pdf))
        assert part is None and kind == "none"

    def test_text_attachment_is_not_used_as_the_body(self):
        """A .txt attachment must not be shown instead of the real body."""
        txt = (b"TEXT", b"PLAIN", (b"NAME", b"log.txt"), None, None, b"7BIT", 9, 1,
               None, (b"attachment", (b"FILENAME", b"log.txt")), None, None)
        struct = (txt, HTML_PART, b"MIXED", (b"BOUNDARY", b"b"), None, None, None)
        part, kind = choose_body_part(walk_bodystructure(struct))
        assert (part.part_id, kind) == ("2", "html-converted")


class TestDecoding:
    def test_base64(self):
        part = walk_bodystructure(
            (b"TEXT", b"PLAIN", (b"CHARSET", b"utf-8"), None, None, b"BASE64", 8, 1,
             None, None, None, None)
        )[0]
        assert decode_body(b"aGVsbG8gd29ybGQ=", part) == "hello world"

    def test_quoted_printable_and_charset(self):
        part = walk_bodystructure(
            (b"TEXT", b"PLAIN", (b"CHARSET", b"iso-8859-1"), None, None,
             b"QUOTED-PRINTABLE", 8, 1, None, None, None, None)
        )[0]
        assert decode_body(b"caf=E9", part) == "café"

    def test_unknown_charset_does_not_raise(self):
        part = walk_bodystructure(
            (b"TEXT", b"PLAIN", (b"CHARSET", b"x-nonsense"), None, None, b"7BIT", 2, 1,
             None, None, None, None)
        )[0]
        assert decode_body(b"hi", part) == "hi"

    def test_malformed_base64_falls_back_to_raw(self):
        part = walk_bodystructure(
            (b"TEXT", b"PLAIN", (b"CHARSET", b"utf-8"), None, None, b"BASE64", 3, 1,
             None, None, None, None)
        )[0]
        assert decode_body(b"!!!not base64!!!", part)

    def test_rfc2047_header(self):
        assert decode_header(b"=?utf-8?B?SGVsbG8gd29ybGQ=?=") == "Hello world"
        assert decode_header(b"plain subject") == "plain subject"

    def test_encoded_attachment_filename(self):
        part = walk_bodystructure(
            (b"APPLICATION", b"PDF", (b"NAME", b"=?utf-8?B?ZmFjdHVyYS5wZGY=?="), None, None,
             b"BASE64", 10, None, None, None, None)
        )[0]
        assert part.filename == "factura.pdf"


class TestTruncate:
    def test_short_text_untouched(self):
        assert truncate("hello", 100) == ("hello", False)

    def test_long_text_marked(self):
        body, was_truncated = truncate("x" * 500, 100)
        assert was_truncated and "[...truncated...]" in body and len(body) < 200

    def test_zero_disables(self):
        assert truncate("x" * 500, 0) == ("x" * 500, False)
