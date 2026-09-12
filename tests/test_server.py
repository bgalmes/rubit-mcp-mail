import pytest

import rubit_mcp_mail.server as server
from rubit_mcp_mail.config import Account, Config
from rubit_mcp_mail.secrets import SecretStore
from rubit_mcp_mail.session import Session


@pytest.fixture
def session(tmp_path):
    account = Account(
        name="x", provider="generic", email="a@b.c", host="h", disabled_tools=["list_folders"]
    )
    return Session(config=Config(accounts={"x": account}), store=SecretStore(tmp_path / "s.json"))


@pytest.fixture
def use_session(monkeypatch, session):
    monkeypatch.setattr(server, "_session", session)
    return session


@pytest.fixture
def write_session(tmp_path):
    account = Account(
        name="x",
        provider="generic",
        email="a@b.c",
        host="h",
        allow_write=True,
        enabled_write_tools=["mark_read"],
    )
    return Session(config=Config(accounts={"x": account}), store=SecretStore(tmp_path / "s.json"))


@pytest.fixture
def use_write_session(monkeypatch, write_session):
    monkeypatch.setattr(server, "_session", write_session)
    return write_session


class TestGuarded:
    def test_disabled_tool_is_blocked_without_touching_backend(self, use_session, monkeypatch):
        def fail_if_called(_name):
            raise AssertionError("backend should not be reached for a disabled tool")

        monkeypatch.setattr(use_session, "backend", fail_if_called)
        result = server.list_folders(account="x")
        assert result == "Error: 'list_folders' is disabled for account 'x'"

    def test_enabled_tool_is_not_blocked(self, use_session, monkeypatch):
        monkeypatch.setattr(
            use_session, "backend", lambda _name: (_ for _ in ()).throw(RuntimeError("reached"))
        )
        result = server.list_messages(account="x")
        assert result == "Error: reached"

    def test_unresolvable_account_falls_through_to_normal_error(self, use_session):
        result = server.list_folders(account="does-not-exist")
        assert "Unknown account" in result
        assert "disabled" not in result


class TestGuardedWrite:
    def test_write_access_off_blocks_without_touching_backend(self, use_session, monkeypatch):
        """`session`'s account "x" has allow_write=False (the default)."""

        def fail_if_called(_name):
            raise AssertionError("backend should not be reached when write access is off")

        monkeypatch.setattr(use_session, "backend", fail_if_called)
        result = server.mark_read(handle="h", account="x")
        assert "Write access is disabled for account 'x'" in result

    def test_write_access_on_but_tool_not_enabled_is_blocked(self, tmp_path, monkeypatch):
        account = Account(name="x", provider="generic", email="a@b.c", host="h", allow_write=True)
        session = Session(
            config=Config(accounts={"x": account}), store=SecretStore(tmp_path / "s.json")
        )
        monkeypatch.setattr(server, "_session", session)

        def fail_if_called(_name):
            raise AssertionError("backend should not be reached for a disabled write tool")

        monkeypatch.setattr(session, "backend", fail_if_called)
        result = server.mark_read(handle="h", account="x")
        assert result == "Error: 'mark_read' is disabled for account 'x'"

    def test_enabled_write_tool_is_not_blocked(self, use_write_session, monkeypatch):
        monkeypatch.setattr(
            use_write_session,
            "backend",
            lambda _name: (_ for _ in ()).throw(RuntimeError("reached")),
        )
        result = server.mark_read(handle="h", account="x")
        assert result == "Error: reached"

    def test_move_message_not_in_enabled_write_tools_is_blocked(self, use_write_session):
        """write_session only enables mark_read, not move_message."""
        result = server.move_message(handle="h", folder="junk", account="x")
        assert result == "Error: 'move_message' is disabled for account 'x'"

    def test_unresolvable_account_falls_through_to_normal_error(self, use_session):
        result = server.mark_read(handle="h", account="does-not-exist")
        assert "Unknown account" in result
        assert "disabled" not in result
