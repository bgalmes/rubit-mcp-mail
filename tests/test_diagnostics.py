import pytest

from rubit_mcp_mail.diagnostics import override_keys, run_doctor
from rubit_mcp_mail.secrets import SecretStore

CONFIG = """
[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"

[providers.outlook]
host = "outlook.example.com"
[providers.outlook.oauth]
authority = "https://login.example.com"
scopes = ["a.scope"]
"""


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """A config and a secret store both rooted in tmp_path, keyring disabled."""
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("RUBIT_MCP_MAIL_CONFIG", str(path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
    return path


class TestRunDoctor:
    def test_reports_needs_auth_without_a_credential(self, configured):
        report = run_doctor(connect=False)
        assert report.failures == 1
        account = report.accounts[0]
        assert (account.name, account.auth_state) == ("personal", "needs_auth")
        assert account.auth_detail == "no password stored"
        assert account.connected is False

    def test_reports_ok_once_a_credential_exists(self, configured):
        SecretStore().set("password:personal", "hunter2")
        report = run_doctor(connect=False)
        assert report.accounts[0].auth_state == "ok"
        assert report.failures == 0

    def test_carries_the_config_context(self, configured):
        report = run_doctor(connect=False)
        assert report.config_path == configured
        assert report.provider_overrides == {"outlook": ["host", "oauth.authority", "oauth.scopes"]}
        assert "keyring unavailable" in report.secrets_backend
        assert report.secrets_warning

    def test_narrows_to_the_named_account(self, configured):
        assert [a.name for a in run_doctor(["personal"], connect=False).accounts] == ["personal"]

    def test_unknown_account_is_a_finding_not_an_exception(self, configured):
        report = run_doctor(["nope"], connect=False)
        assert "Unknown account" in (report.accounts[0].error or "")
        assert report.failures == 1

    def test_missing_config_is_flagged_rather_than_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUBIT_MCP_MAIL_CONFIG", str(tmp_path / "absent.toml"))
        report = run_doctor(connect=False)
        assert report.missing_config and not report.config_error

    def test_broken_config_is_reported_in_config_pys_words(self, tmp_path, monkeypatch):
        path = tmp_path / "config.toml"
        path.write_text('[accounts.x]\nprovider = "generic"\nemail = "a@b.co"\n')
        monkeypatch.setenv("RUBIT_MCP_MAIL_CONFIG", str(path))
        report = run_doctor(connect=False)
        assert "needs an explicit `host`" in (report.config_error or "")


class TestOverrideKeys:
    def test_flattens_oauth_subkeys(self):
        assert override_keys({"host": "h", "oauth": {"authority": "a"}}) == [
            "host",
            "oauth.authority",
        ]

    def test_sorted_and_empty_safe(self):
        assert override_keys({"port": 1, "host": "h"}) == ["host", "port"]
        assert override_keys({}) == []
