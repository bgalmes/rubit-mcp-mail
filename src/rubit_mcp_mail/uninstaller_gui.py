"""The uninstall window: a small tkinter confirm-then-report dialog.

Much simpler than installer_gui.Wizard: nothing an uninstall does blocks on
user-facing network interaction the way sign-in does, so there is no worker
thread or event queue here - `apply_uninstall` runs directly on the button
handler.
"""

from __future__ import annotations

from pathlib import Path

from . import __version__
from .installer import default_install_dir
from .secrets import SecretStore
from .uninstaller import UninstallResult, apply_uninstall, console_uninstall

WINDOW_TITLE = "Uninstall rubit-mcp-mail"
PAD = 12

_EXPLANATION = (
    "This removes rubit-mcp-mail: the installed server and settings "
    "programs, your configured accounts, stored credentials, shortcuts, "
    "and its registration with Claude Desktop and Claude Code.\n\n"
    "Downloaded mail attachments are left in place.\n\n"
    "This cannot be undone."
)


class UninstallWindow:
    """One root, one body frame, swapped between a confirm page and a result page."""

    def __init__(
        self,
        root,
        *,
        config_file: Path | None = None,
        install_dir: Path | None = None,
        store: SecretStore | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        self.root = root
        self.config_file = config_file
        self.install_dir = install_dir or default_install_dir()
        self.store = store
        self.exit_code = 1

        root.title(f"{WINDOW_TITLE} — v{__version__}")
        root.minsize(520, 300)
        try:
            ttk.Style().theme_use("clam")
        except Exception:  # noqa: BLE001 - cosmetic only; any theme will do
            pass

        self.body = ttk.Frame(root)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        self._show_confirm()

    def _reset_body(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

    def _show_confirm(self) -> None:
        ttk = self._ttk
        self._reset_body()

        ttk.Label(self.body, text=_EXPLANATION, wraplength=480, justify="left").pack(
            anchor="w", pady=(0, PAD)
        )

        footer = ttk.Frame(self.body)
        footer.pack(fill="x", side="bottom")
        ttk.Button(footer, text="Cancel", command=self._on_cancel).pack(side="right")
        ttk.Button(footer, text="Uninstall", command=self._on_uninstall).pack(
            side="right", padx=(0, 8)
        )

    def _on_cancel(self) -> None:
        self.exit_code = 1
        self.root.destroy()

    def _on_uninstall(self) -> None:
        result = apply_uninstall(
            config_file=self.config_file, install_dir=self.install_dir, store=self.store
        )
        self.exit_code = 0
        self._show_result(result)

    def _show_result(self, result: UninstallResult) -> None:
        tk, ttk = self._tk, self._ttk
        self._reset_body()

        ttk.Label(self.body, text="Uninstalled.", font=("TkDefaultFont", 13, "bold")).pack(
            anchor="w", pady=(0, 8)
        )

        wrapper = ttk.Frame(self.body)
        wrapper.pack(fill="both", expand=True)
        text = tk.Text(wrapper, wrap="word", height=11, relief="flat", background="#f4f4f4")
        scroll = ttk.Scrollbar(wrapper, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", "\n".join(result.notes))
        text.configure(state="disabled")

        footer = ttk.Frame(self.body)
        footer.pack(fill="x", side="bottom", pady=(PAD, 0))
        ttk.Button(footer, text="Close", command=self.root.destroy).pack(side="right")


def run(
    *,
    config_file: Path | None = None,
    install_dir: Path | None = None,
    force_console: bool = False,
) -> int:
    """Open the uninstall window, falling back to the console version if it can't.

    A missing display or a Python built without Tk are both ordinary
    situations rather than errors, exactly as in `installer_gui.run`.
    """
    if not force_console:
        try:
            import tkinter as tk

            root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - ImportError or TclError
            print(f"No graphical display available ({exc}); continuing in the terminal.")
        else:
            window = UninstallWindow(root, config_file=config_file, install_dir=install_dir)
            root.mainloop()
            return window.exit_code

    return console_uninstall(config_file=config_file, install_dir=install_dir)
