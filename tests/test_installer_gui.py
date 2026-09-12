"""What can be checked without a display.

The window itself needs a real Tk, which build machines and CI containers
usually lack, so the widget test skips rather than failing there. The routing
below is what guarantees a machine with no display still gets a working setup.
"""

import pytest

from rubit_mcp_mail import installer_gui


class TestConsoleFallback:
    def test_force_console_never_opens_a_window(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(installer_gui, "console_wizard", lambda **kw: calls.append(kw) or 0)

        code = installer_gui.run(force_console=True, config_file=tmp_path / "config.toml")

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
        monkeypatch.setattr(installer_gui, "console_wizard", lambda **kw: 7)

        code = installer_gui.run(config_file=tmp_path / "config.toml")

        assert code == 7
        assert "no graphical display" in capsys.readouterr().out.lower()


class TestTheWindow:
    def test_pages_advance(self, tmp_path):
        tk = pytest.importorskip("tkinter")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            pytest.skip(f"no display available: {exc}")

        try:
            wizard = installer_gui.Wizard(root, config_file=tmp_path / "config.toml")
            assert wizard._page == "welcome"

            wizard._on_next()
            assert wizard._page == "account"

            # An empty form must not advance, and must say why.
            wizard._on_next()
            assert wizard._page == "account"
            assert wizard.var_status.get()

            wizard.var_email.set("me@outlook.com")
            assert wizard.var_name.get() == "me"  # suggested from the address
            assert installer_gui.validate_plan(wizard._current_plan()) is None
        finally:
            root.destroy()
