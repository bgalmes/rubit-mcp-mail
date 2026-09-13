"""What the shortcut files say, checkable on any platform.

The two halves that are easy to get wrong - .desktop syntax and PowerShell
quoting - are pure functions here, so they are tested directly rather than by
running a desktop environment.
"""

from pathlib import Path

from rubit_mcp_mail import shortcuts

GUI = Path("/home/someone/.local/share/rubit-mcp-mail/bin/rubit-mcp-mail-gui")


class TestDesktopEntry:
    def test_launches_the_binary_with_no_terminal(self):
        entry = shortcuts.desktop_entry(GUI)

        assert f'Exec="{GUI}"' in entry
        assert "Terminal=false" in entry
        assert "Type=Application" in entry

    def test_exec_is_quoted_so_a_space_in_the_path_survives(self):
        entry = shortcuts.desktop_entry(Path("/home/a b/bin/rubit-mcp-mail-gui"))

        assert 'Exec="/home/a b/bin/rubit-mcp-mail-gui"' in entry

    def test_arguments_follow_the_quoted_path(self):
        entry = shortcuts.desktop_entry(Path("/usr/bin/rubit-mcp-mail"), "gui")

        assert 'Exec="/usr/bin/rubit-mcp-mail" gui' in entry

    def test_no_arguments_leaves_no_trailing_space(self):
        assert f'Exec="{GUI}"\n' in shortcuts.desktop_entry(GUI)

    def test_icon_name_is_used(self):
        assert "Icon=mail-message-new" in shortcuts.desktop_entry(GUI, icon="mail-message-new")


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
        assert len(entries) == 1
        assert "/old/" not in entries[0].read_text()

    def test_an_unwritable_directory_is_reported_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(shortcuts.shutil, "which", lambda _name: None)

        def refuse(*_args, **_kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr(Path, "write_text", refuse)

        notes = shortcuts.create_shortcuts(GUI)

        assert any("Could not create the application menu entry" in note for note in notes)


class TestWindowsScript:
    def test_targets_the_binary_and_both_folders(self):
        script = shortcuts.windows_shortcut_script(Path(r"C:\Users\a\rubit-mcp-mail-gui.exe"))

        assert r"C:\Users\a\rubit-mcp-mail-gui.exe" in script
        assert "'Programs', 'Desktop'" in script
        assert "CreateShortcut" in script

    def test_a_quote_in_the_path_cannot_break_out_of_the_literal(self):
        script = shortcuts.windows_shortcut_script(Path("C:/o'brien/gui.exe"))

        # Doubled, which is how a single-quoted PowerShell string escapes one.
        assert "'C:/o''brien/gui.exe'" in script

    def test_arguments_are_set_separately_from_the_target(self):
        script = shortcuts.windows_shortcut_script(Path("C:/bin/rubit-mcp-mail.exe"), "gui")

        assert "$link.Arguments = 'gui'" in script


class TestNeverRaises:
    def test_a_failure_becomes_a_note(self, monkeypatch):
        def explode(*_args, **_kwargs):
            raise RuntimeError("no desktop here")

        monkeypatch.setattr(shortcuts, "_create_linux", explode)
        monkeypatch.setattr(shortcuts, "_create_windows", explode)
        monkeypatch.setattr(shortcuts.sys, "platform", "linux")

        notes = shortcuts.create_shortcuts(GUI)

        assert notes == ["Could not create shortcuts (no desktop here)."]
