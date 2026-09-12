from rubit_mcp_mail.permissions import (
    TOOL_LABELS,
    TOOL_NAMES,
    WRITE_TOOL_LABELS,
    WRITE_TOOL_NAMES,
)


def test_list_accounts_excluded():
    assert "list_accounts" not in TOOL_NAMES


def test_no_duplicates():
    assert len(TOOL_NAMES) == len(set(TOOL_NAMES))


def test_labels_match_names():
    assert set(TOOL_LABELS) == set(TOOL_NAMES)


def test_write_tools_have_no_overlap_with_read_tools():
    assert not set(WRITE_TOOL_NAMES) & set(TOOL_NAMES)


def test_write_labels_match_names():
    assert set(WRITE_TOOL_LABELS) == set(WRITE_TOOL_NAMES)


def test_no_delete_tool():
    assert not any("delete" in tool or "trash" in tool for tool in WRITE_TOOL_NAMES)
