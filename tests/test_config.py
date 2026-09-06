import pytest

from rubit_mcp_mail.config import Config, load_config
from rubit_mcp_mail.secrets import SecretStore
from rubit_mcp_mail.session import Session, safe_filename


@pytest.fixture
def write_config(tmp_path):
    def _write(body):
        path = tmp_path / "config.toml"
        path.write_text(body)
        return path

    return _write


class TestConfig:
    def test_loads_accounts(self, write_config):
        config = load_config(
            write_config("""
[accounts.outlook]
provider = "outlook"
email = "me@outlook.com"
client_id = "abc"
[accounts.work]
provider = "generic"
email = "me@example.com"
host = "imap.example.com"
port = 1993
""")
        )
        assert set(config.accounts) == {"outlook", "work"}
        assert config.account("outlook").profile.host == "outlook.office365.com"
        assert config.account("outlook").profile.auth == "oauth_microsoft"
        work = config.account("work").profile
        assert (work.host, work.port, work.auth) == ("imap.example.com", 1993, "password")

    def test_outlook_requires_client_id(self, write_config):
        with pytest.raises(ValueError, match="client_id"):
            load_config(write_config('[accounts.x]\nprovider="outlook"\nemail="a@b.c"'))

    def test_generic_requires_host(self, write_config):
        with pytest.raises(ValueError, match="host"):
            load_config(write_config('[accounts.x]\nprovider="generic"\nemail="a@b.c"'))

    def test_unknown_provider_lists_known(self, write_config):
        with pytest.raises(ValueError, match="Known providers: generic, outlook"):
            load_config(write_config('[accounts.x]\nprovider="nope"\nemail="a@b.c"'))

    def test_typo_in_top_level_key_is_caught(self, write_config):
        with pytest.raises(ValueError, match="Unknown key"):
            load_config(write_config('downlod_dir = "/tmp"'))

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "absent.toml")


class TestDisabledTools:
    def test_loads_disabled_tools(self, write_config):
        config = load_config(write_config('''
[accounts.x]
provider = "generic"
email = "a@b.c"
host = "h"
disabled_tools = ["read_message", "get_attachment"]
'''))
        assert config.account("x").disabled_tools == ["read_message", "get_attachment"]

    def test_defaults_to_empty(self, write_config):
        config = load_config(write_config('[accounts.x]\nprovider="generic"\nemail="a@b.c"\nhost="h"'))
        assert config.account("x").disabled_tools == []

    def test_unknown_tool_name_is_caught(self, write_config):
        with pytest.raises(ValueError, match="unknown tool.*send_mail"):
            load_config(write_config(
                '[accounts.x]\nprovider="generic"\nemail="a@b.c"\nhost="h"\n'
                'disabled_tools = ["send_mail"]'
            ))


class TestProviderOverrides:
    def test_overrides_host_and_oauth_fields(self, write_config):
        config = load_config(
            write_config("""
[accounts.x]
provider = "outlook"
email = "a@b.c"
client_id = "abc"

[providers.outlook]
host = "outlook.example.net"

[providers.outlook.oauth]
authority = "https://login.example.net/common"
scopes = ["https://example.net/IMAP.AccessAsUser.All"]
""")
        )
        profile = config.account("x").profile
        assert profile.host == "outlook.example.net"
        assert profile.oauth is not None
        assert profile.oauth.authority == "https://login.example.net/common"
        assert profile.oauth.scopes == ["https://example.net/IMAP.AccessAsUser.All"]

    def test_override_does_not_leak_to_other_providers(self, write_config):
        config = load_config(
            write_config("""
[accounts.outlook]
provider = "outlook"
email = "a@b.c"
client_id = "abc"
[accounts.other]
provider = "generic"
email = "d@e.f"
host = "imap.example.com"

[providers.outlook]
host = "outlook.example.net"
""")
        )
        assert config.account("outlook").profile.host == "outlook.example.net"
        assert config.account("other").profile.host == "imap.example.com"

    def test_unknown_override_key_is_caught(self, write_config):
        with pytest.raises(ValueError, match="Unknown provider override"):
            load_config(
                write_config(
                    '[providers.outlook]\nnope = "x"\n'
                    '[accounts.x]\nprovider="outlook"\nemail="a@b.c"\nclient_id="abc"'
                )
            )

    def test_unknown_provider_name_is_caught(self, write_config):
        with pytest.raises(ValueError, match="Known providers: generic, outlook"):
            load_config(write_config('[providers.gmial]\nhost = "x"'))


class TestAccountResolution:
    def _config(self, write_config, body):
        return load_config(write_config(body))

    ONE = '[accounts.only]\nprovider="generic"\nemail="a@b.c"\nhost="h"'
    TWO = ONE + '\n[accounts.second]\nprovider="generic"\nemail="d@e.f"\nhost="h2"'

    def test_single_account_is_the_default(self, write_config):
        config = self._config(write_config, self.ONE)
        assert config.account(None).name == "only"

    def test_ambiguous_when_several(self, write_config):
        config = self._config(write_config, self.TWO)
        with pytest.raises(ValueError, match="only, second"):
            config.account(None)

    def test_unknown_name_lists_configured(self, write_config):
        config = self._config(write_config, self.TWO)
        with pytest.raises(ValueError, match="Configured: only, second"):
            config.account("typo")

    def test_no_accounts_at_all(self):
        with pytest.raises(ValueError, match="No accounts configured"):
            Config().account(None)


class TestSafeFilename:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("report.pdf", "report.pdf"),
            ("../../etc/passwd", "passwd"),
            ("..\\..\\windows\\win.ini", "win.ini"),
            ("/absolute/path.txt", "path.txt"),
            ("", "attachment"),
            ("...", "attachment"),
            (".hidden", "hidden"),
        ],
    )
    def test_sanitization(self, given, expected):
        assert safe_filename(given) == expected

    def test_length_is_capped(self):
        assert len(safe_filename("a" * 500 + ".pdf")) <= 180


class TestDownloadPath:
    def _session(self, tmp_path):
        return Session(
            config=Config(download_dir=tmp_path / "dl"), store=SecretStore(tmp_path / "s.json")
        )

    def test_writes_inside_download_dir(self, tmp_path):
        path = self._session(tmp_path).download_path("report.pdf")
        assert path.parent == (tmp_path / "dl").resolve()

    def test_traversal_cannot_escape(self, tmp_path):
        path = self._session(tmp_path).download_path("../../../../etc/passwd")
        assert path.parent == (tmp_path / "dl").resolve()
        assert path.name == "passwd"

    def test_existing_file_is_not_clobbered(self, tmp_path):
        session = self._session(tmp_path)
        first = session.download_path("a.pdf")
        first.write_bytes(b"original")
        second = session.download_path("a.pdf")
        assert second != first and second.name == "a-1.pdf"
        assert first.read_bytes() == b"original"


class TestSecretStore:
    def test_file_roundtrip_and_permissions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
        path = tmp_path / "nested" / "secrets.json"
        store = SecretStore(path)
        assert store.get("missing") is None
        store.set("token:x", "s3cret")
        assert store.get("token:x") == "s3cret"
        assert oct(path.stat().st_mode)[-3:] == "600"
        assert oct(path.parent.stat().st_mode)[-3:] == "700"
        store.delete("token:x")
        assert store.get("token:x") is None

    def test_corrupt_file_is_survivable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
        path = tmp_path / "secrets.json"
        path.write_text("{not json")
        assert SecretStore(path).get("anything") is None
