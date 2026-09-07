import tomllib

from rubit_mcp_mail.permissions import TOOL_NAMES, WRITE_TOOL_NAMES
from rubit_mcp_mail.permissions_editor import (
    apply_toggles,
    apply_write_toggles,
    checkbox_name,
    write_disabled_tools,
    write_parent_checkbox_name,
    write_tool_checkbox_name,
    write_write_permissions,
)

CONFIG = """# a hand-written comment that must survive
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
"""


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
        personal_block = text[text.index("[accounts.personal]") :]
        original_personal_block = original[original.index("[accounts.personal]") :]
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


class TestApplyWriteToggles:
    def test_nothing_posted_means_write_disabled_and_no_tools_enabled(self):
        assert apply_write_toggles(["x"], {}) == {"x": (False, [])}

    def test_parent_checked_alone_enables_no_tools(self):
        posted = {write_parent_checkbox_name("x"): ["on"]}
        assert apply_write_toggles(["x"], posted) == {"x": (True, [])}

    def test_tool_checked_without_parent_still_records_it(self):
        """Storage keeps fine-grained choices even if the parent is off -
        enforcement of "parent off wins" happens at call time, not storage."""
        posted = {write_tool_checkbox_name("x", "mark_read"): ["on"]}
        assert apply_write_toggles(["x"], posted) == {"x": (False, ["mark_read"])}

    def test_parent_and_all_tools_checked(self):
        posted = {write_parent_checkbox_name("x"): ["on"]}
        posted.update({write_tool_checkbox_name("x", tool): ["on"] for tool in WRITE_TOOL_NAMES})
        assert apply_write_toggles(["x"], posted) == {"x": (True, sorted(WRITE_TOOL_NAMES))}

    def test_multiple_accounts_are_independent(self):
        posted = {write_parent_checkbox_name("a"): ["on"]}
        posted[write_tool_checkbox_name("a", "mark_read")] = ["on"]
        assert apply_write_toggles(["a", "b"], posted) == {
            "a": (True, ["mark_read"]),
            "b": (False, []),
        }


class TestWriteWritePermissions:
    def _write(self, tmp_path, body=CONFIG):
        path = tmp_path / "config.toml"
        path.write_text(body)
        return path

    def test_changes_target_account(self, tmp_path):
        path = self._write(tmp_path)
        write_write_permissions(path, {"outlook": (True, ["mark_read"])})
        raw = tomllib.loads(path.read_text())
        assert raw["accounts"]["outlook"]["allow_write"] is True
        assert raw["accounts"]["outlook"]["enabled_write_tools"] == ["mark_read"]

    def test_false_and_empty_omit_keys(self, tmp_path):
        path = self._write(tmp_path)
        write_write_permissions(path, {"outlook": (False, [])})
        text = path.read_text()
        assert "allow_write" not in text
        assert "enabled_write_tools" not in text

    def test_comments_survive(self, tmp_path):
        path = self._write(tmp_path)
        write_write_permissions(path, {"outlook": (True, ["move_message"])})
        text = path.read_text()
        assert "# a hand-written comment that must survive" in text
        assert "# another comment, on the second account" in text

    def test_unknown_account_in_updates_is_ignored(self, tmp_path):
        path = self._write(tmp_path)
        original = path.read_text()
        write_write_permissions(path, {"nope": (True, ["mark_read"])})
        assert path.read_text() == original
