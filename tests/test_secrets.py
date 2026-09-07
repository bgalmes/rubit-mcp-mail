"""Secret backend selection, and the diagnosis it has to make possible.

A credential written to the OS keyring is invisible to a process that cannot
reach the keyring - which is every MCP server launched by a GUI client with a
stripped environment. That failure is indistinguishable from an expired token
unless the store says which backend it is using, so these tests pin that down.
"""

import pytest

from rubit_mcp_mail.auth.oauth_microsoft import MicrosoftDeviceCodeAuth
from rubit_mcp_mail.config import Account
from rubit_mcp_mail.secrets import SecretStore


@pytest.fixture
def file_store(tmp_path, monkeypatch):
    monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
    return SecretStore(path=tmp_path / "secrets.json")


def test_file_backend_round_trip(file_store):
    assert file_store.get("k") is None
    file_store.set("k", "v")
    assert file_store.get("k") == "v"
    file_store.delete("k")
    assert file_store.get("k") is None


def test_file_backend_is_owner_only(file_store):
    file_store.set("k", "v")
    assert file_store._path.stat().st_mode & 0o777 == 0o600


def test_backend_name_reports_the_file_and_why(file_store):
    assert str(file_store._path) in file_store.backend_name
    assert file_store.unavailable_reason == "disabled by RUBIT_MCP_MAIL_NO_KEYRING"


def test_missing_dbus_is_named_as_the_reason(tmp_path, monkeypatch):
    monkeypatch.delenv("RUBIT_MCP_MAIL_NO_KEYRING", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setattr(
        "keyring.get_keyring", lambda: __import__("keyring").backends.fail.Keyring()
    )
    store = SecretStore(path=tmp_path / "secrets.json")
    assert "DBUS_SESSION_BUS_ADDRESS" in (store.unavailable_reason or "")


def test_auth_status_explains_an_unreachable_keyring(file_store):
    account = Account(name="outlook", provider="outlook", email="you@outlook.com", client_id="cid")
    state, detail = MicrosoftDeviceCodeAuth(account, file_store).status()

    assert state == "needs_auth"
    # Not just "no cached token": it has to say where it looked and why there.
    assert str(file_store._path) in (detail or "")
    assert "RUBIT_MCP_MAIL_NO_KEYRING" in (detail or "")


def test_auth_status_ok_path_is_unaffected(file_store, monkeypatch):
    account = Account(name="outlook", provider="outlook", email="you@outlook.com", client_id="cid")
    strategy = MicrosoftDeviceCodeAuth(account, file_store)
    file_store.set(strategy.secret_key, "{}")
    monkeypatch.setattr(
        MicrosoftDeviceCodeAuth,
        "_app",
        lambda self, cache: _FakeApp(account.email),
    )

    assert strategy.status() == ("ok", None)


class _FakeApp:
    def __init__(self, username):
        self._username = username

    def get_accounts(self):
        return [{"username": self._username}]

    def acquire_token_silent(self, scopes, account):
        return {"access_token": "tok"}
