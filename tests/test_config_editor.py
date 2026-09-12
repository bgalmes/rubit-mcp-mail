import pytest
import tomllib

from rubit_mcp_mail.config import load_config
from rubit_mcp_mail.config_editor import (
    apply_toggles,
    checkbox_name,
    load_document,
    remove_account,
    remove_provider_override,
    save_document,
    set_download_dir,
    upsert_account,
    upsert_provider_override,
    validate_account_form,
    write_disabled_tools,
)
from rubit_mcp_mail.permissions import TOOL_NAMES

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


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    return path


class TestAccountCrud:
    def test_add_account_is_loadable(self, config_file):
        doc = load_document(config_file)
        upsert_account(
            doc, "work", {"provider": "generic", "email": "me@work.com", "host": "imap.work.com"}
        )
        save_document(config_file, doc)
        config = load_config(config_file)
        assert config.account("work").profile.host == "imap.work.com"
        assert set(config.accounts) == {"outlook", "personal", "work"}

    def test_edit_leaves_the_rest_of_the_file_alone(self, config_file):
        original = config_file.read_text()
        doc = load_document(config_file)
        upsert_account(doc, "personal", {"port": 1993})
        save_document(config_file, doc)

        text = config_file.read_text()
        assert "# a hand-written comment that must survive" in text
        assert (
            text[: text.index("[accounts.personal]")]
            == original[: original.index("[accounts.personal]")]
        )
        assert load_config(config_file).account("personal").profile.port == 1993

    def test_edit_keeps_disabled_tools(self, config_file):
        doc = load_document(config_file)
        upsert_account(doc, "outlook", {"email": "new@outlook.com"})
        save_document(config_file, doc)
        assert load_config(config_file).account("outlook").disabled_tools == ["read_message"]

    def test_empty_value_removes_the_key_rather_than_blanking_it(self, config_file):
        doc = load_document(config_file)
        upsert_account(doc, "personal", {"port": 1993})
        save_document(config_file, doc)
        doc = load_document(config_file)
        upsert_account(doc, "personal", {"port": ""})
        save_document(config_file, doc)
        assert "port" not in config_file.read_text()
        assert load_config(config_file).account("personal").profile.port == 993

    def test_remove_account_keeps_the_others(self, config_file):
        doc = load_document(config_file)
        remove_account(doc, "personal")
        save_document(config_file, doc)
        config = load_config(config_file)
        assert set(config.accounts) == {"outlook"}
        assert config.account("outlook").client_id == "abc"

    def test_download_dir_round_trip(self, config_file):
        doc = load_document(config_file)
        set_download_dir(doc, "~/Mail")
        save_document(config_file, doc)
        assert str(load_config(config_file).download_dir).endswith("Mail")

    def test_absent_file_edits_as_an_empty_document(self, tmp_path):
        path = tmp_path / "sub" / "config.toml"
        doc = load_document(path)
        upsert_account(doc, "x", {"provider": "generic", "email": "a@b.co", "host": "h.co"})
        save_document(path, doc)
        assert load_config(path).account("x").email == "a@b.co"


class TestSaveDocumentRejectsBadWrites:
    def test_invalid_edit_leaves_the_file_byte_identical(self, config_file):
        original = config_file.read_text()
        doc = load_document(config_file)
        upsert_account(doc, "broken", {"provider": "generic", "email": "a@b.co"})
        with pytest.raises(ValueError, match="host"):
            save_document(config_file, doc)
        assert config_file.read_text() == original

    def test_no_temp_file_is_left_behind(self, config_file):
        doc = load_document(config_file)
        upsert_account(doc, "broken", {"provider": "outlook", "email": "a@b.co"})
        with pytest.raises(ValueError):
            save_document(config_file, doc)
        assert list(config_file.parent.iterdir()) == [config_file]


class TestProviderOverrides:
    def test_write_and_apply(self, config_file):
        doc = load_document(config_file)
        upsert_provider_override(
            doc,
            "outlook",
            {"host": "outlook.example.com", "port": 1993, "authority": "https://login.example.com"},
        )
        save_document(config_file, doc)
        config = load_config(config_file)
        profile = config.account("outlook").profile
        assert (profile.host, profile.port) == ("outlook.example.com", 1993)
        assert profile.oauth is not None
        assert profile.oauth.authority == "https://login.example.com"

    def test_scopes_are_written_as_a_list(self, config_file):
        doc = load_document(config_file)
        upsert_provider_override(doc, "outlook", {"scopes": ["a.scope", "b.scope"]})
        save_document(config_file, doc)
        raw = tomllib.loads(config_file.read_text())
        assert raw["providers"]["outlook"]["oauth"]["scopes"] == ["a.scope", "b.scope"]

    def test_emptying_every_field_removes_the_table(self, config_file):
        doc = load_document(config_file)
        upsert_provider_override(doc, "outlook", {"host": "outlook.example.com"})
        save_document(config_file, doc)
        doc = load_document(config_file)
        upsert_provider_override(doc, "outlook", {})
        save_document(config_file, doc)
        assert "providers" not in config_file.read_text()
        assert load_config(config_file).providers == {}

    def test_remove_override(self, config_file):
        doc = load_document(config_file)
        upsert_provider_override(doc, "outlook", {"host": "h.example.com"})
        save_document(config_file, doc)
        doc = load_document(config_file)
        remove_provider_override(doc, "outlook")
        save_document(config_file, doc)
        assert load_config(config_file).providers == {}


class TestValidateAccountForm:
    GENERIC = {"provider": "generic", "email": "a@b.co", "host": "h.co"}

    def test_accepts_and_normalises(self):
        cleaned = validate_account_form(
            "work", dict(self.GENERIC, port=" 1993 ", ssl="false", client_id="  ")
        )
        assert cleaned["port"] == 1993
        assert cleaned["ssl"] is False
        assert cleaned["client_id"] is None

    def test_blank_ssl_means_provider_default(self):
        assert validate_account_form("work", dict(self.GENERIC, ssl=""))["ssl"] is None

    @pytest.mark.parametrize("name", ["", "  ", "has space", "quote'd", "a/b"])
    def test_rejects_unusable_account_names(self, name):
        with pytest.raises(ValueError, match="account name"):
            validate_account_form(name, self.GENERIC)

    @pytest.mark.parametrize("email", ["", "nope", "a@b", "two @ signs@x.co"])
    def test_rejects_malformed_email(self, email):
        with pytest.raises(ValueError, match="email address"):
            validate_account_form("work", dict(self.GENERIC, email=email))

    @pytest.mark.parametrize("port", ["nope", "0", "70000", "-1"])
    def test_rejects_bad_port(self, port):
        with pytest.raises(ValueError, match="[Pp]ort"):
            validate_account_form("work", dict(self.GENERIC, port=port))

    def test_rejects_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            validate_account_form("work", dict(self.GENERIC, provider="fastmail"))

    def test_rejects_bad_ssl(self):
        with pytest.raises(ValueError, match="SSL must be true or false"):
            validate_account_form("work", dict(self.GENERIC, ssl="maybe"))

    def test_missing_host_uses_config_pys_own_words(self):
        with pytest.raises(ValueError, match="needs an explicit `host`"):
            validate_account_form("work", {"provider": "generic", "email": "a@b.co"})

    def test_missing_client_id_uses_config_pys_own_words(self):
        with pytest.raises(ValueError, match="Azure app registration"):
            validate_account_form("work", {"provider": "outlook", "email": "a@b.co"})
