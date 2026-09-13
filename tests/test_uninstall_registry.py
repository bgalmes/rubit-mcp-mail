"""What gets written to the registry, checkable without touching it."""

from pathlib import Path

from rubit_mcp_mail import uninstall_registry as ureg

GUI = Path(r"C:\Users\a\AppData\Local\Programs\rubit-mcp-mail\rubit-mcp-mail-gui.exe")
INSTALL_DIR = GUI.parent


class TestRegistryValues:
    def test_uninstall_string_quotes_the_executable_and_passes_uninstall(self):
        values = ureg.registry_values(GUI, INSTALL_DIR)

        assert values["UninstallString"] == f'"{GUI}" uninstall'

    def test_points_at_the_install_location(self):
        values = ureg.registry_values(GUI, INSTALL_DIR)

        assert values["InstallLocation"] == str(INSTALL_DIR)
        assert values["DisplayIcon"] == str(GUI)

    def test_declares_no_modify_or_repair(self):
        values = ureg.registry_values(GUI, INSTALL_DIR)

        assert values["NoModify"] == 1
        assert values["NoRepair"] == 1


class TestNoopOffWindows:
    def test_register_does_nothing(self, monkeypatch):
        monkeypatch.setattr(ureg.sys, "platform", "linux")
        ureg.register(GUI, INSTALL_DIR)  # must not raise, must not touch winreg

    def test_unregister_does_nothing(self, monkeypatch):
        monkeypatch.setattr(ureg.sys, "platform", "linux")
        ureg.unregister()  # must not raise, must not touch winreg
