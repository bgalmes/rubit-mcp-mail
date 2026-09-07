import pytest
import tomllib

from rubit_mcp_mail.config import add_account, load_config

CONFIG = """# a hand-written comment that must survive
download_dir = "~/Downloads/rubit-mcp-mail"

[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "abc"
disabled_tools = ["read_message"]
"""


def _existing(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    return path


class TestCreatingTheFile:
    def test_creates_config_with_a_download_dir(self, tmp_path):
        path = tmp_path / "nested" / "config.toml"
        add_account(path, "outlook", "outlook", "you@outlook.com", client_id="abc")
        raw = tomllib.loads(path.read_text())
        assert raw["download_dir"] == "~/Downloads/rubit-mcp-mail"
        assert raw["accounts"]["outlook"]["email"] == "you@outlook.com"

    def test_written_config_loads(self, tmp_path):
        path = tmp_path / "config.toml"
        add_account(path, "personal", "generic", "me@fastmail.com", host="imap.fastmail.com")
        account = load_config(path).account("personal")
        assert account.email == "me@fastmail.com"
        assert account.profile.host == "imap.fastmail.com"


class TestMergingIntoAnExistingFile:
    def test_other_accounts_and_comments_survive(self, tmp_path):
        path = _existing(tmp_path)
        add_account(path, "personal", "generic", "me@fastmail.com", host="imap.fastmail.com")
        text = path.read_text()
        assert "# a hand-written comment that must survive" in text
        assert sorted(load_config(path).accounts) == ["outlook", "personal"]

    def test_rerunning_updates_in_place(self, tmp_path):
        path = _existing(tmp_path)
        add_account(path, "outlook", "outlook", "new@outlook.com", client_id="xyz")
        text = path.read_text()
        assert text.count("[accounts.outlook]") == 1
        account = load_config(path).account("outlook")
        assert (account.email, account.client_id) == ("new@outlook.com", "xyz")

    def test_keys_we_do_not_manage_are_left_alone(self, tmp_path):
        path = _existing(tmp_path)
        add_account(path, "outlook", "outlook", "you@outlook.com", client_id="abc")
        assert load_config(path).account("outlook").disabled_tools == ["read_message"]

    def test_stale_key_from_a_changed_provider_is_dropped(self, tmp_path):
        # A host left over from a generic account would otherwise silently
        # override the new provider's own server.
        path = tmp_path / "config.toml"
        add_account(path, "acct", "generic", "me@fastmail.com", host="imap.fastmail.com")
        add_account(path, "acct", "outlook", "me@outlook.com", client_id="abc")
        assert "imap.fastmail.com" not in path.read_text()
        assert load_config(path).account("acct").profile.host == "outlook.office365.com"


class TestValidation:
    def test_generic_without_a_host_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="needs an explicit `host`"):
            add_account(tmp_path / "config.toml", "acct", "generic", "me@fastmail.com")

    def test_outlook_without_a_client_id_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="client_id"):
            add_account(tmp_path / "config.toml", "acct", "outlook", "me@outlook.com")

    def test_unknown_provider_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown provider"):
            add_account(tmp_path / "config.toml", "acct", "carrier-pigeon", "me@example.com")

    def test_a_refused_account_writes_nothing(self, tmp_path):
        path = _existing(tmp_path)
        before = path.read_text()
        with pytest.raises(ValueError):
            add_account(path, "broken", "generic", "me@fastmail.com")
        assert path.read_text() == before

    def test_a_refused_account_does_not_create_the_file(self, tmp_path):
        path = tmp_path / "config.toml"
        with pytest.raises(ValueError):
            add_account(path, "broken", "generic", "me@fastmail.com")
        assert not path.exists()
