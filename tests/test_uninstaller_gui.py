"""What can be checked without a display.

Mirrors test_installer_gui.py: the window itself needs a real Tk, which
build machines and CI containers usually lack, so the fallback routing is
what's checked here.
"""

from rubit_mcp_mail import uninstaller_gui


class TestConsoleFallback:
    def test_force_console_never_opens_a_window(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(
            uninstaller_gui, "console_uninstall", lambda **kw: calls.append(kw) or 0
        )

        code = uninstaller_gui.run(force_console=True, config_file=tmp_path / "config.toml")

        assert code == 0
        assert calls == [{"config_file": tmp_path / "config.toml", "install_dir": None}]

    def test_falls_back_when_tkinter_is_unavailable(self, monkeypatch, tmp_path, capsys):
        import builtins

        real_import = builtins.__import__

        def no_tkinter(name, *args, **kwargs):
            if name == "tkinter":
                raise ImportError("no _tkinter")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_tkinter)
        monkeypatch.setattr(uninstaller_gui, "console_uninstall", lambda **kw: 7)

        code = uninstaller_gui.run(config_file=tmp_path / "config.toml")

        assert code == 7
        assert "no graphical display" in capsys.readouterr().out.lower()
