import json
import sys
from pathlib import Path

import pytest

from rubit_mcp_mail import claude_registration as cr

SERVER = Path("/opt/rubit-mcp-mail/rubit-mcp-mail")


class TestConfigPath:
    def test_linux_honours_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert cr.claude_desktop_config_path() == tmp_path / "Claude" / "claude_desktop_config.json"

    def test_windows_uses_appdata(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert cr.claude_desktop_config_path() == tmp_path / "Claude" / "claude_desktop_config.json"

    def test_detection_follows_the_directory(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert not cr.claude_desktop_detected()
        (tmp_path / "Claude").mkdir()
        assert cr.claude_desktop_detected()

    def test_windows_finds_an_msix_packaged_install(self, monkeypatch, tmp_path):
        # The exact directory shape confirmed on a real Windows machine: an
        # MSIX-packaged Claude Desktop redirects its "roaming" data under
        # LOCALAPPDATA\Packages\Claude_<publisher-hash>\LocalCache\Roaming\.
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.delenv("APPDATA", raising=False)
        package_dir = (
            tmp_path / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
        )
        package_dir.mkdir(parents=True)
        config = package_dir / "claude_desktop_config.json"
        config.write_text("{}")

        assert cr.claude_desktop_detected()
        assert cr.claude_desktop_config_path() == config

    def test_windows_finds_an_msix_install_before_the_config_file_exists(
        self, monkeypatch, tmp_path
    ):
        # A fresh MSIX install may have the package directory but no config
        # file yet - that must still count as "detected".
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.delenv("APPDATA", raising=False)
        package_dir = (
            tmp_path / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
        )
        package_dir.mkdir(parents=True)

        assert cr.claude_desktop_detected()

    def test_windows_falls_back_to_the_classic_layout(self, monkeypatch, tmp_path):
        # No Packages directory at all - an unpackaged (classic) installer.
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "does-not-exist"))
        monkeypatch.setenv("APPDATA", str(tmp_path))
        (tmp_path / "Claude").mkdir()

        assert cr.claude_desktop_detected()
        assert cr.claude_desktop_config_path() == tmp_path / "Claude" / "claude_desktop_config.json"

    def test_windows_neither_layout_present_means_not_detected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "does-not-exist"))
        monkeypatch.setenv("APPDATA", str(tmp_path / "also-does-not-exist"))

        assert not cr.claude_desktop_detected()


class TestDesktopEntry:
    def test_no_env_block_when_the_keyring_works(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert "env" not in cr.desktop_entry(SERVER, needs_no_keyring=False)

    def test_env_block_when_the_keyring_is_unreachable(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        entry = cr.desktop_entry(SERVER, needs_no_keyring=True)
        assert entry["env"] == {"RUBIT_MCP_MAIL_NO_KEYRING": "1"}

    def test_windows_never_gets_an_env_block(self, monkeypatch):
        # The Credential Manager is reachable from every process there.
        monkeypatch.setattr(sys, "platform", "win32")
        assert "env" not in cr.desktop_entry(SERVER, needs_no_keyring=True)

    def test_command_and_args(self):
        entry = cr.desktop_entry(SERVER, needs_no_keyring=False)
        assert entry["command"] == str(SERVER)
        assert entry["args"] == ["serve"]


class TestRegisterClaudeDesktop:
    def test_creates_the_file_when_absent(self, tmp_path):
        path = tmp_path / "Claude" / "claude_desktop_config.json"
        cr.register_claude_desktop(SERVER, needs_no_keyring=False, config_path=path)
        assert json.loads(path.read_text())["mcpServers"]["rubit-mail"]["args"] == ["serve"]

    def test_other_servers_and_keys_survive(self, tmp_path):
        path = tmp_path / "claude_desktop_config.json"
        path.write_text(
            json.dumps(
                {
                    "globalShortcut": "Ctrl+Space",
                    "mcpServers": {"other": {"command": "/usr/bin/other"}},
                }
            )
        )
        cr.register_claude_desktop(SERVER, needs_no_keyring=False, config_path=path)
        document = json.loads(path.read_text())
        assert document["globalShortcut"] == "Ctrl+Space"
        assert document["mcpServers"]["other"] == {"command": "/usr/bin/other"}
        assert "rubit-mail" in document["mcpServers"]

    def test_rerunning_replaces_only_our_entry(self, tmp_path):
        path = tmp_path / "claude_desktop_config.json"
        cr.register_claude_desktop(SERVER, needs_no_keyring=False, config_path=path)
        newer = Path("/opt/elsewhere/rubit-mcp-mail")
        cr.register_claude_desktop(newer, needs_no_keyring=False, config_path=path)
        servers = json.loads(path.read_text())["mcpServers"]
        assert list(servers) == ["rubit-mail"]
        assert servers["rubit-mail"]["command"] == str(newer)

    def test_a_config_without_mcpservers_is_handled(self, tmp_path):
        path = tmp_path / "claude_desktop_config.json"
        path.write_text(json.dumps({"theme": "dark"}))
        cr.register_claude_desktop(SERVER, needs_no_keyring=False, config_path=path)
        document = json.loads(path.read_text())
        assert document["theme"] == "dark"
        assert "rubit-mail" in document["mcpServers"]

    def test_unreadable_json_is_reported_not_clobbered(self, tmp_path):
        path = tmp_path / "claude_desktop_config.json"
        path.write_text("{ not json at all")
        with pytest.raises(ValueError, match="not valid JSON"):
            cr.register_claude_desktop(SERVER, needs_no_keyring=False, config_path=path)
        assert path.read_text() == "{ not json at all"

    def test_no_temp_file_is_left_behind(self, tmp_path):
        path = tmp_path / "claude_desktop_config.json"
        cr.register_claude_desktop(SERVER, needs_no_keyring=False, config_path=path)
        assert [p.name for p in tmp_path.iterdir()] == ["claude_desktop_config.json"]


class TestRegisterClaudeCode:
    def test_removes_before_adding(self, monkeypatch):
        calls = []

        class Result:
            returncode = 0
            stdout = "Added"
            stderr = ""

        monkeypatch.setattr(cr.subprocess, "run", lambda argv, **kw: calls.append(argv) or Result())
        ok, output = cr.register_claude_code(SERVER)

        assert ok and output == "Added"
        assert calls[0] == ["claude", "mcp", "remove", "rubit-mail", "--scope", "user"]
        assert calls[1] == [
            "claude",
            "mcp",
            "add",
            "rubit-mail",
            "--scope",
            "user",
            "--",
            str(SERVER),
            "serve",
        ]

    def test_a_failing_add_is_reported(self, monkeypatch):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "boom"

        monkeypatch.setattr(cr.subprocess, "run", lambda argv, **kw: Result())
        ok, output = cr.register_claude_code(SERVER)
        assert not ok and output == "boom"
