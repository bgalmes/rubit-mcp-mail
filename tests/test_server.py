import pytest

import rubit_mcp_mail.server as server
from rubit_mcp_mail.config import Account, Config
from rubit_mcp_mail.secrets import SecretStore
from rubit_mcp_mail.session import Session


@pytest.fixture
def session(tmp_path):
    account = Account(name="x", provider="generic", email="a@b.c", host="h", disabled_tools=["list_folders"])
    return Session(config=Config(accounts={"x": account}), store=SecretStore(tmp_path / "s.json"))


@pytest.fixture
def use_session(monkeypatch, session):
    monkeypatch.setattr(server, "_session", session)
    return session


class TestGuarded:
    def test_disabled_tool_is_blocked_without_touching_backend(self, use_session, monkeypatch):
        def fail_if_called(_name):
            raise AssertionError("backend should not be reached for a disabled tool")

        monkeypatch.setattr(use_session, "backend", fail_if_called)
        result = server.list_folders(account="x")
        assert result == "Error: 'list_folders' is disabled for account 'x'"

    def test_enabled_tool_is_not_blocked(self, use_session, monkeypatch):
        monkeypatch.setattr(use_session, "backend", lambda _name: (_ for _ in ()).throw(RuntimeError("reached")))
        result = server.list_messages(account="x")
        assert result == "Error: reached"

    def test_unresolvable_account_falls_through_to_normal_error(self, use_session):
        result = server.list_folders(account="does-not-exist")
        assert "Unknown account" in result
        assert "disabled" not in result
