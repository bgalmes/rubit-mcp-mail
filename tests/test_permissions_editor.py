import tomllib

from rubit_mcp_mail.permissions import TOOL_NAMES
from rubit_mcp_mail.permissions_editor import apply_toggles, checkbox_name, write_disabled_tools

CONFIG = '''# a hand-written comment that must survive
download_dir = "~/Downloads/rubit-mcp-mail"

[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "abc"
disabled_tools = ["read_message"]

# another comment, on the second account
[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
'''


class TestApplyToggles:
    def test_all_checked_means_nothing_disabled(self):
        posted = {checkbox_name("x", tool): ["on"] for tool in TOOL_NAMES}
        assert apply_toggles(["x"], posted) == {"x": []}

    def test_unchecked_box_is_disabled(self):
        posted = {tool: ["on"] for tool in TOOL_NAMES if tool != "read_message"}
        posted = {checkbox_name("x", k): v for k, v in posted.items()}
        assert apply_toggles(["x"], posted) == {"x": ["read_message"]}

    def test_no_posted_keys_disables_everything(self):
        assert apply_toggles(["x"], {}) == {"x": sorted(TOOL_NAMES)}

    def test_multiple_accounts_are_independent(self):
        posted = {checkbox_name("a", tool): ["on"] for tool in TOOL_NAMES}
        assert apply_toggles(["a", "b"], posted) == {"a": [], "b": sorted(TOOL_NAMES)}


class TestWriteDisabledTools:
    def _write(self, tmp_path, body=CONFIG):
        path = tmp_path / "config.toml"
        path.write_text(body)
        return path

    def test_changes_target_account(self, tmp_path):
        path = self._write(tmp_path)
        write_disabled_tools(path, {"outlook": ["get_attachment"]})
        raw = tomllib.loads(path.read_text())
        assert raw["accounts"]["outlook"]["disabled_tools"] == ["get_attachment"]

    def test_untouched_account_is_unchanged(self, tmp_path):
        path = self._write(tmp_path)
        original = path.read_text()
        write_disabled_tools(path, {"outlook": ["get_attachment"]})
        text = path.read_text()
        personal_block = text[text.index("[accounts.personal]"):]
        original_personal_block = original[original.index("[accounts.personal]"):]
        assert personal_block == original_personal_block

    def test_comments_survive(self, tmp_path):
        path = self._write(tmp_path)
        write_disabled_tools(path, {"outlook": []})
        text = path.read_text()
        assert "# a hand-written comment that must survive" in text
        assert "# another comment, on the second account" in text

    def test_emptied_list_removes_key_rather_than_writing_empty_array(self, tmp_path):
        path = self._write(tmp_path)
        write_disabled_tools(path, {"outlook": []})
        text = path.read_text()
        assert "disabled_tools" not in text

    def test_unknown_account_in_updates_is_ignored(self, tmp_path):
        path = self._write(tmp_path)
        original = path.read_text()
        write_disabled_tools(path, {"nope": ["read_message"]})
        assert path.read_text() == original
