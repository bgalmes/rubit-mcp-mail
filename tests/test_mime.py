from imapclient.response_parser import parse_fetch_response

from rubit_mcp_mail.mime import (
    attachments_from,
    body_candidates,
    decode_body,
    decode_header,
    normalize_spacing,
    truncate,
    walk_bodystructure,
)


def ids_for(raw_bodystructure: bytes):
    """Part ids as they come out of IMAPClient's own response parser.

    Going through the real parser is the point: hand-written tuples are what let
    a walker that mismodelled the wire format pass its tests for months.
    """
    response = parse_fetch_response([b"1 (BODYSTRUCTURE " + raw_bodystructure + b")"])
    struct = response[1][b"BODYSTRUCTURE"]
    return [(p.part_id, p.content_type) for p in walk_bodystructure(struct)]


def ranked(struct):
    """The (part id, format) shortlist read_message will work down."""
    return [(p.part_id, fmt) for p, fmt in body_candidates(walk_bodystructure(struct))]


TEXT_PART = (
    b"TEXT",
    b"PLAIN",
    (b"CHARSET", b"utf-8"),
    None,
    None,
    b"7BIT",
    100,
    5,
    None,
    None,
    None,
    None,
)
HTML_PART = (
    b"TEXT",
    b"HTML",
    (b"CHARSET", b"utf-8"),
    None,
    None,
    b"QUOTED-PRINTABLE",
    300,
    10,
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
    40000,
    None,
    (b"attachment", (b"FILENAME", b"report.pdf")),
    None,
    None,
)

ALTERNATIVE = ([TEXT_PART, HTML_PART], b"ALTERNATIVE", (b"BOUNDARY", b"x1"), None, None, None)
MIXED = ([ALTERNATIVE, PDF_PART], b"MIXED", (b"BOUNDARY", b"x0"), None, None, None)


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
        assert ranked(MIXED)[0] == ("1.1", "text")

    def test_html_is_kept_as_a_fallback_behind_plain(self):
        """Plain wins, but html must stay on the list in case plain is a placeholder."""
        assert ranked(MIXED) == [("1.1", "text"), ("1.2", "html-converted")]

    def test_falls_back_to_html(self):
        html_only = ([HTML_PART], b"ALTERNATIVE", (b"BOUNDARY", b"b"), None, None, None)
        assert ranked(html_only) == [("1", "html-converted")]

    def test_empty_plain_part_is_not_a_candidate(self):
        """The newsletter case: a 0-byte plain leg must not shadow the html one."""
        empty = (
            b"TEXT",
            b"PLAIN",
            (b"CHARSET", b"utf-8"),
            None,
            None,
            b"7BIT",
            0,
            1,
            None,
            None,
            None,
            None,
        )
        struct = ([empty, HTML_PART], b"ALTERNATIVE", (b"BOUNDARY", b"b"), None, None, None)
        assert ranked(struct) == [("2", "html-converted")]

    def test_no_text_part_at_all(self):
        only_pdf = ([PDF_PART], b"MIXED", (b"BOUNDARY", b"b"), None, None, None)
        assert ranked(only_pdf) == []

    def test_text_attachment_is_not_used_as_the_body(self):
        """A .txt attachment must not be shown instead of the real body."""
        txt = (
            b"TEXT",
            b"PLAIN",
            (b"NAME", b"log.txt"),
            None,
            None,
            b"7BIT",
            9,
            1,
            None,
            (b"attachment", (b"FILENAME", b"log.txt")),
            None,
            None,
        )
        struct = ([txt, HTML_PART], b"MIXED", (b"BOUNDARY", b"b"), None, None, None)
        assert ranked(struct) == [("2", "html-converted")]

    def test_unusual_text_subtype_beats_showing_nothing(self):
        md = (
            b"TEXT",
            b"MARKDOWN",
            (b"CHARSET", b"utf-8"),
            None,
            None,
            b"7BIT",
            40,
            3,
            None,
            None,
            None,
            None,
        )
        struct = ([md, PDF_PART], b"MIXED", (b"BOUNDARY", b"b"), None, None, None)
        assert ranked(struct) == [("1", "text")]


class TestDecoding:
    def test_base64(self):
        part = walk_bodystructure(
            (
                b"TEXT",
                b"PLAIN",
                (b"CHARSET", b"utf-8"),
                None,
                None,
                b"BASE64",
                8,
                1,
                None,
                None,
                None,
                None,
            )
        )[0]
        assert decode_body(b"aGVsbG8gd29ybGQ=", part) == "hello world"

    def test_quoted_printable_and_charset(self):
        part = walk_bodystructure(
            (
                b"TEXT",
                b"PLAIN",
                (b"CHARSET", b"iso-8859-1"),
                None,
                None,
                b"QUOTED-PRINTABLE",
                8,
                1,
                None,
                None,
                None,
                None,
            )
        )[0]
        assert decode_body(b"caf=E9", part) == "café"

    def test_unknown_charset_does_not_raise(self):
        part = walk_bodystructure(
            (
                b"TEXT",
                b"PLAIN",
                (b"CHARSET", b"x-nonsense"),
                None,
                None,
                b"7BIT",
                2,
                1,
                None,
                None,
                None,
                None,
            )
        )[0]
        assert decode_body(b"hi", part) == "hi"

    def test_malformed_base64_falls_back_to_raw(self):
        part = walk_bodystructure(
            (
                b"TEXT",
                b"PLAIN",
                (b"CHARSET", b"utf-8"),
                None,
                None,
                b"BASE64",
                3,
                1,
                None,
                None,
                None,
                None,
            )
        )[0]
        assert decode_body(b"!!!not base64!!!", part)

    def test_rfc2047_header(self):
        assert decode_header(b"=?utf-8?B?SGVsbG8gd29ybGQ=?=") == "Hello world"
        assert decode_header(b"plain subject") == "plain subject"

    def test_encoded_attachment_filename(self):
        part = walk_bodystructure(
            (
                b"APPLICATION",
                b"PDF",
                (b"NAME", b"=?utf-8?B?ZmFjdHVyYS5wZGY=?="),
                None,
                None,
                b"BASE64",
                10,
                None,
                None,
                None,
                None,
            )
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


class TestRealServerShapes:
    """Part ids against BODYSTRUCTURE bytes as a server actually sends them."""

    def test_alternative_children_are_top_level(self):
        """Captured from Outlook: the newsletter that came back with an empty body.

        The children of a top-level multipart/alternative are parts 1 and 2. The
        walker used to report them as 1.1 and 1.2, so BODY[1.1] fetched NIL.
        """
        raw = (
            b'(("text" "plain" ("charset" "utf-8") NIL NIL "quoted-printable" '
            b'13828 457 NIL NIL NIL NIL)("text" "html" ("charset" "utf-8") NIL '
            b'NIL "quoted-printable" 64061 1462 NIL NIL NIL NIL) "alternative" '
            b'("boundary" "w1-U3dKo") NIL NIL)'
        )
        assert ids_for(raw) == [("1", "text/plain"), ("2", "text/html")]

    def test_alternative_nested_in_mixed(self):
        raw = (
            b'((("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 10 1 NIL NIL '
            b'NIL NIL)("text" "html" ("charset" "utf-8") NIL NIL "7bit" 20 1 NIL '
            b'NIL NIL NIL) "alternative" NIL NIL NIL)("application" "pdf" '
            b'("name" "sponsor.pdf") NIL NIL "base64" 100 NIL ("attachment" '
            b'("filename" "sponsor.pdf")) NIL NIL) "mixed" NIL NIL NIL)'
        )
        assert ids_for(raw) == [
            ("1.1", "text/plain"),
            ("1.2", "text/html"),
            ("2", "application/pdf"),
        ]

    def test_single_part_message(self):
        raw = b'("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 42 2 NIL NIL NIL NIL)'
        assert ids_for(raw) == [("1", "text/plain")]

    def test_flat_tuples_still_walk(self):
        """The fallback branch, for hand-written structures with no wrapper list."""
        flat = (TEXT_PART, HTML_PART, b"ALTERNATIVE", (b"BOUNDARY", b"x"), None, None)
        assert [p.part_id for p in walk_bodystructure(flat)] == ["1", "2"]


class TestNormalizeSpacing:
    def test_padding_ribbon_collapses(self):
        text = "faster" + "\u00a0\u200c" * 40 + "end"
        assert normalize_spacing(text) == "faster end"

    def test_lone_nbsp_in_prose_survives(self):
        assert normalize_spacing("100\u00a0km") == "100\u00a0km"

    def test_paragraph_break_is_not_swallowed(self):
        """A run must never match across a newline, or paragraphs would merge."""
        assert normalize_spacing("one\u00a0\n\ntwo\u00a0") == "one\u00a0\n\ntwo\u00a0"


class TestTruncateKeepsReferences:
    def _doc(self, paragraphs=40):
        body = "\n\n".join(f"Headline [{i}] and some prose here." for i in range(1, paragraphs))
        refs = "\n".join(
            f"   [{i}]: https://example.com/{'x' * 60}/{i}" for i in range(1, paragraphs)
        )
        return body + "\n\n" + refs

    def test_referenced_targets_survive_the_cut(self):
        body, was_truncated = truncate(self._doc(), 1500)
        assert was_truncated
        assert "[...truncated...]" in body
        kept = [n for n in range(1, 40) if f"[{n}]:" in body]
        assert kept, "every reference definition was cut away"
        for number in kept:
            assert f"[{number}]" in body.split("[...truncated...]")[0]

    def test_stays_within_the_budget(self):
        for limit in (400, 1500, 4000):
            body, _ = truncate(self._doc(), limit)
            assert len(body) <= limit, f"{len(body)} > {limit}"

    def test_plain_text_without_references_is_unchanged_behaviour(self):
        body, was_truncated = truncate("x" * 500, 100)
        assert was_truncated and len(body) <= 100
