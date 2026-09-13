import sys
from pathlib import Path

import pytest

from rubit_mcp_mail import uninstaller
from rubit_mcp_mail.config import add_account
from rubit_mcp_mail.secrets import SecretStore

SERVER = Path("/opt/rubit-mcp-mail/rubit-mcp-mail")


class FakeStrategy:
    def __init__(self, account, store):
        self.secret_key = f"password:{account.name}"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
    return SecretStore(path=tmp_path / "secrets.json")


@pytest.fixture
def build_auth(monkeypatch):
    monkeypatch.setattr(uninstaller, "build_auth", FakeStrategy)


@pytest.fixture
def no_clients(monkeypatch):
    monkeypatch.setattr(uninstaller.claude_registration, "claude_code_available", lambda: False)
    monkeypatch.setattr(uninstaller.claude_registration, "unregister_claude_desktop", lambda: None)


@pytest.fixture
def no_shortcuts(monkeypatch):
    monkeypatch.setattr(uninstaller.shortcuts, "remove_shortcuts", lambda: [])


@pytest.fixture
def no_registry(monkeypatch):
    monkeypatch.setattr(uninstaller.uninstall_registry, "unregister", lambda: None)


class TestRemoveConfigAndSecrets:
    def test_deletes_exactly_the_two_files(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("download_dir = '~/Downloads'\n")
        secrets_file = tmp_path / "secrets.json"
        secrets_file.write_text("{}")
        store = SecretStore(path=secrets_file)

        uninstaller._remove_config_and_secrets(config_file, store)

        assert not config_file.exists()
        assert not secrets_file.exists()

    def test_does_not_touch_an_unrelated_sibling_file(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("x")
        other = tmp_path / "notes.txt"
        other.write_text("keep me")
        store = SecretStore(path=tmp_path / "secrets.json")

        uninstaller._remove_config_and_secrets(config_file, store)

        assert other.exists()

    def test_tidies_an_empty_directory_afterwards(self, tmp_path):
        config_dir = tmp_path / "rubit-mcp-mail"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"
        config_file.write_text("x")
        store = SecretStore(path=config_dir / "secrets.json")

        uninstaller._remove_config_and_secrets(config_file, store)

        assert not config_dir.exists()

    def test_a_missing_config_is_a_noop_not_an_error(self, tmp_path):
        config_file = tmp_path / "config.toml"
        store = SecretStore(path=tmp_path / "secrets.json")

        notes = uninstaller._remove_config_and_secrets(config_file, store)

        assert notes == []


@pytest.mark.usefixtures("no_clients", "no_shortcuts", "no_registry")
class TestApplyUninstall:
    def test_removes_stored_credentials_for_every_account(
        self, tmp_path, store, build_auth, monkeypatch
    ):
        config_file = tmp_path / "config.toml"
        add_account(config_file, "work", "generic", "me@example.com", host="imap.example.com")
        store.set("password:work", "s3cret")
        monkeypatch.setattr(uninstaller, "_remove_install_dir", lambda install_dir: None)

        uninstaller.apply_uninstall(config_file=config_file, store=store)

        assert store.get("password:work") is None

    def test_deletes_the_config_and_secrets_files(self, tmp_path, store, monkeypatch):
        config_file = tmp_path / "config.toml"
        config_file.write_text("download_dir = '~/Downloads'\n")
        monkeypatch.setattr(uninstaller, "_remove_install_dir", lambda install_dir: None)

        uninstaller.apply_uninstall(config_file=config_file, store=store)

        assert not config_file.exists()

    def test_removes_the_install_directory(self, tmp_path, store, monkeypatch):
        install_dir = tmp_path / "bin"
        install_dir.mkdir()
        (install_dir / "rubit-mcp-mail").write_bytes(b"binary")
        monkeypatch.setattr(uninstaller, "is_frozen", lambda: False)

        result = uninstaller.apply_uninstall(
            config_file=tmp_path / "config.toml", install_dir=install_dir, store=store
        )

        assert not install_dir.exists()
        assert any("Removed" in note for note in result.notes)

    def test_windows_frozen_schedules_cleanup_instead_of_deleting_immediately(
        self, tmp_path, store, monkeypatch
    ):
        install_dir = tmp_path / "bin"
        install_dir.mkdir()
        monkeypatch.setattr(uninstaller, "is_frozen", lambda: True)
        monkeypatch.setattr(sys, "platform", "win32")
        scheduled = []
        monkeypatch.setattr(uninstaller, "_spawn_windows_cleanup", lambda d: scheduled.append(d))

        result = uninstaller.apply_uninstall(
            config_file=tmp_path / "config.toml", install_dir=install_dir, store=store
        )

        assert scheduled == [install_dir]
        assert install_dir.exists()  # deferred, not deleted here
        assert any("will be removed" in note for note in result.notes)

    def test_notes_that_downloads_are_left_alone(self, tmp_path, store, monkeypatch):
        monkeypatch.setattr(uninstaller, "_remove_install_dir", lambda install_dir: None)

        result = uninstaller.apply_uninstall(config_file=tmp_path / "config.toml", store=store)

        assert any("Downloads" in note for note in result.notes)

    def test_a_clean_machine_does_not_crash(self, tmp_path, store, monkeypatch):
        monkeypatch.setattr(uninstaller, "_remove_install_dir", lambda install_dir: None)

        result = uninstaller.apply_uninstall(
            config_file=tmp_path / "does-not-exist.toml", store=store
        )

        assert result.notes  # at least the "downloads kept" note


class TestUnregistersClaudeClients:
    def test_claude_code_is_unregistered_when_available(
        self, tmp_path, store, no_shortcuts, no_registry, monkeypatch
    ):
        monkeypatch.setattr(uninstaller, "_remove_install_dir", lambda install_dir: None)
        monkeypatch.setattr(uninstaller.claude_registration, "claude_code_available", lambda: True)
        monkeypatch.setattr(
            uninstaller.claude_registration, "unregister_claude_code", lambda: (True, "Removed")
        )
        monkeypatch.setattr(
            uninstaller.claude_registration, "unregister_claude_desktop", lambda: None
        )

        result = uninstaller.apply_uninstall(config_file=tmp_path / "config.toml", store=store)

        assert any("Claude Code: unregistered" in note for note in result.notes)

    def test_not_available_is_skipped_without_a_note(
        self, tmp_path, store, no_shortcuts, no_registry, monkeypatch
    ):
        monkeypatch.setattr(uninstaller, "_remove_install_dir", lambda install_dir: None)
        monkeypatch.setattr(uninstaller.claude_registration, "claude_code_available", lambda: False)
        monkeypatch.setattr(
            uninstaller.claude_registration, "unregister_claude_desktop", lambda: None
        )

        result = uninstaller.apply_uninstall(config_file=tmp_path / "config.toml", store=store)

        assert not any("Claude Code" in note for note in result.notes)


class TestWindowsCleanupScript:
    def test_retries_rather_than_a_single_fixed_delay(self):
        script = uninstaller.windows_cleanup_script(Path(r"C:\Users\a\rubit-mcp-mail"))

        assert "for (" in script
        assert "Remove-Item" in script

    def test_targets_the_install_dir(self):
        script = uninstaller.windows_cleanup_script(Path(r"C:\Users\a\rubit-mcp-mail"))

        assert r"C:\Users\a\rubit-mcp-mail" in script

    def test_a_quote_cannot_break_out_of_the_literal(self):
        script = uninstaller.windows_cleanup_script(Path("C:/o'brien/rubit-mcp-mail"))

        assert "'C:/o''brien/rubit-mcp-mail'" in script

    def test_deletes_itself_last(self):
        script = uninstaller.windows_cleanup_script(Path(r"C:\bin"))

        assert "$PSCommandPath" in script
