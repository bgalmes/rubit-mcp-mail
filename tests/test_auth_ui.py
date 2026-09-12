import pytest

from rubit_mcp_mail.auth import base
from rubit_mcp_mail.auth.password import PasswordAuth
from rubit_mcp_mail.config import Account
from rubit_mcp_mail.secrets import SecretStore

ACCOUNT = Account(name="personal", provider="generic", email="me@fastmail.com", host="imap.f.com")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
    return SecretStore(path=tmp_path / "secrets.json")


class FakeUI:
    def __init__(self, password=""):
        self.password = password
        self.flows = []

    def device_code(self, flow):
        self.flows.append(flow)

    def ask_password(self, account):
        self.account = account
        return self.password


class TestPasswordAuth:
    def test_takes_the_password_from_the_injected_ui(self, store):
        ui = FakeUI("s3cret")
        message = PasswordAuth(ACCOUNT, store).interactive_setup(ui)
        assert store.get("password:personal") == "s3cret"
        assert ui.account is ACCOUNT
        assert "stored" in message

    def test_surrounding_whitespace_is_dropped(self, store):
        PasswordAuth(ACCOUNT, store).interactive_setup(FakeUI("  s3cret  "))
        assert store.get("password:personal") == "s3cret"

    def test_an_empty_password_stores_nothing(self, store):
        with pytest.raises(ValueError, match="nothing stored"):
            PasswordAuth(ACCOUNT, store).interactive_setup(FakeUI(""))
        assert store.get("password:personal") is None

    def test_without_a_ui_it_still_prompts_on_the_console(self, store, monkeypatch, capsys):
        # What `rubit-mcp-mail auth` has always done, and must keep doing.
        monkeypatch.setattr(base.getpass, "getpass", lambda prompt: "typed")
        PasswordAuth(ACCOUNT, store).interactive_setup()
        assert store.get("password:personal") == "typed"
        printed = capsys.readouterr().out
        assert "personal" in printed and "imap.f.com" in printed


class TestConsoleAuthUI:
    def test_device_code_prints_the_message_and_the_wait(self, capsys):
        base.ConsoleAuthUI().device_code({"message": "Go to example.com and enter ABC-123"})
        printed = capsys.readouterr().out
        assert "Go to example.com and enter ABC-123" in printed
        assert "Waiting for you" in printed

    def test_ask_password_reads_it_without_echoing(self, monkeypatch, capsys):
        monkeypatch.setattr(base.getpass, "getpass", lambda prompt: " hunter2 ")
        assert base.ConsoleAuthUI().ask_password(ACCOUNT) == "hunter2"
        assert "hunter2" not in capsys.readouterr().out
