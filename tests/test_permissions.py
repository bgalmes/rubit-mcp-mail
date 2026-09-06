from rubit_mcp_mail.permissions import TOOL_LABELS, TOOL_NAMES


def test_list_accounts_excluded():
    assert "list_accounts" not in TOOL_NAMES


def test_no_duplicates():
    assert len(TOOL_NAMES) == len(set(TOOL_NAMES))


def test_labels_match_names():
    assert set(TOOL_LABELS) == set(TOOL_NAMES)
