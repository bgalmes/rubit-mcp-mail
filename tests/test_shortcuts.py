"""What the shortcut files say, checkable on any platform.

The two halves that are easy to get wrong - .desktop syntax and PowerShell
quoting - are pure functions here, so they are tested directly rather than by
running a desktop environment.

Those pure tests use PurePosixPath/PureWindowsPath rather than Path so that
each one asserts the string that platform really produces, whichever platform
the suite happens to be running on. The tests that write files are a different
matter and are skipped off POSIX - see the classes below.
"""

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from rubit_mcp_mail import shortcuts

GUI = Path("/home/someone/.local/share/rubit-mcp-mail/bin/rubit-mcp-mail-gui")

#: These write .desktop files, chmod them and read the mode back. Windows has
#: no equivalent - `create_shortcuts` dispatches to PowerShell there, which is
#: covered by the script tests at the bottom of this file.
linux_behaviour = pytest.mark.skipif(
    sys.platform == "win32", reason="Linux desktop entries; Windows takes the PowerShell path"
)


class TestDesktopEntry:
    def test_launches_the_binary_with_no_terminal(self):
        entry = shortcuts.desktop_entry(GUI)

        assert f'Exec="{GUI}"' in entry
        assert "Terminal=false" in entry
        assert "Type=Application" in entry

    def test_exec_is_quoted_so_a_space_in_the_path_survives(self):
        entry = shortcuts.desktop_entry(PurePosixPath("/home/a b/bin/rubit-mcp-mail-gui"))

        assert 'Exec="/home/a b/bin/rubit-mcp-mail-gui"' in entry

    def test_arguments_follow_the_quoted_path(self):
        entry = shortcuts.desktop_entry(PurePosixPath("/usr/bin/rubit-mcp-mail"), "gui")

        assert 'Exec="/usr/bin/rubit-mcp-mail" gui' in entry

    def test_no_arguments_leaves_no_trailing_space(self):
        assert f'Exec="{GUI}"\n' in shortcuts.desktop_entry(GUI)

    def test_icon_name_is_used(self):
        assert "Icon=mail-message-new" in shortcuts.desktop_entry(GUI, icon="mail-message-new")


@linux_behaviour
class TestCreateLinux:
    def test_writes_an_executable_entry_under_xdg_data_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)

        notes = shortcuts.create_shortcuts(GUI)

        path = tmp_path / "applications" / "rubit-mcp-mail.desktop"
        assert path.is_file()
        assert path.stat().st_mode & 0o111, "desktop entry must be executable"
        assert f'Exec="{GUI}"' in path.read_text()
        assert any("Application menu" in note for note in notes)

    def test_rerunning_setup_replaces_rather_than_duplicates(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)

        shortcuts.create_shortcuts(Path("/old/rubit-mcp-mail-gui"))
        shortcuts.create_shortcuts(GUI)

        entries = list((tmp_path / "applications").iterdir())
        assert len(entries) == 2  # the settings entry and the uninstall entry
        assert not any("/old/" in entry.read_text() for entry in entries)

    def test_also_writes_an_uninstall_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)

        shortcuts.create_shortcuts(GUI)

        path = tmp_path / "applications" / f"{shortcuts.UNINSTALL_SHORTCUT_NAME}.desktop"
        assert path.is_file()
        assert f'Exec="{GUI}" uninstall' in path.read_text()

    def test_an_unwritable_directory_is_reported_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)

        def refuse(*_args, **_kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr(Path, "write_text", refuse)

        notes = shortcuts.create_shortcuts(GUI)

        assert any("Could not create the application menu entry" in note for note in notes)


@linux_behaviour
class TestRemoveLinux:
    def test_removes_both_entries_and_the_icon(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)
        shortcuts.create_shortcuts(GUI)
        apps = tmp_path / "applications"
        assert list(apps.iterdir())  # something got created first

        notes = shortcuts.remove_shortcuts()

        assert list(apps.iterdir()) == []
        assert any("removed" in note.lower() for note in notes)

    def test_a_clean_machine_is_a_noop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)

        notes = shortcuts.remove_shortcuts()

        assert not any("removed" in note.lower() for note in notes)

    def test_an_unremovable_entry_is_reported_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)
        shortcuts.create_shortcuts(GUI)

        def refuse(*_args, **_kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr(Path, "unlink", refuse)

        notes = shortcuts.remove_shortcuts()

        assert any("Could not remove" in note for note in notes)


class TestWindowsScript:
    def test_targets_the_binary_and_both_folders(self):
        script = shortcuts.windows_shortcut_script(Path(r"C:\Users\a\rubit-mcp-mail-gui.exe"))

        assert r"C:\Users\a\rubit-mcp-mail-gui.exe" in script
        assert "'Programs', 'Desktop'" in script
        assert "CreateShortcut" in script

    def test_a_quote_in_the_path_cannot_break_out_of_the_literal(self):
        script = shortcuts.windows_shortcut_script(PureWindowsPath("C:/o'brien/gui.exe"))

        # Doubled, which is how a single-quoted PowerShell string escapes one.
        assert r"'C:\o''brien\gui.exe'" in script

    def test_arguments_are_set_separately_from_the_target(self):
        script = shortcuts.windows_shortcut_script(Path("C:/bin/rubit-mcp-mail.exe"), "gui")

        assert "$link.Arguments = 'gui'" in script


class TestWindowsRemovalScript:
    def test_targets_the_same_name_and_both_folders(self):
        script = shortcuts.windows_shortcut_removal_script()

        assert f"{shortcuts.SHORTCUT_NAME}.lnk" in script
        assert "'Programs', 'Desktop'" in script
        assert "Remove-Item" in script


class TestNeverRaises:
    def test_a_failure_becomes_a_note(self, monkeypatch):
        def explode(*_args, **_kwargs):
            raise RuntimeError("no desktop here")

        monkeypatch.setattr(shortcuts, "_create_linux", explode)
        monkeypatch.setattr(shortcuts, "_create_windows", explode)
        monkeypatch.setattr(shortcuts.sys, "platform", "linux")

        notes = shortcuts.create_shortcuts(GUI)

        assert notes == ["Could not create shortcuts (no desktop here)."]

    def test_removal_failure_becomes_a_note(self, monkeypatch):
        def explode(*_args, **_kwargs):
            raise RuntimeError("no desktop here")

        monkeypatch.setattr(shortcuts, "_remove_linux", explode)
        monkeypatch.setattr(shortcuts, "_remove_windows", explode)
        monkeypatch.setattr(shortcuts.sys, "platform", "linux")

        notes = shortcuts.remove_shortcuts()

        assert notes == ["Could not remove shortcuts (no desktop here)."]
