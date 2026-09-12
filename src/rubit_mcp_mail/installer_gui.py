"""The setup window: a small tkinter wizard over `installer.py`.

Only this module knows about widgets. Everything it actually does lives in
`installer`, so the console fallback and this window take the same code path.

Threading rule, because tkinter has no tolerance for breaking it: the blocking
work (device-code polling, IMAP, registering with Claude) runs on a worker
thread, and the worker only ever posts messages onto `self._events`. Widgets
are touched exclusively from `_drain_events`, which runs on the main thread.
"""

from __future__ import annotations

import queue
import threading
import webbrowser
from pathlib import Path

from .config import Account
from .installer import (
    KNOWN_IMAP_HOSTS,
    SetupPlan,
    SetupResult,
    apply_setup,
    console_wizard,
    default_client_id,
    existing_accounts,
    plan_from_existing,
    suggest_account_name,
    validate_plan,
)

WINDOW_TITLE = "rubit-mcp-mail Setup"
PAD = 12


class Wizard:
    """The whole window. One root, one body frame, pages swapped inside it."""

    def __init__(
        self,
        root,
        *,
        config_file: Path | None = None,
        install_dir: Path | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        self.root = root
        self.config_file = config_file
        self.install_dir = install_dir
        self.exit_code = 1

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._password = ""
        self._accounts: dict[str, Account] = existing_accounts(config_file)
        # Last account name we filled in ourselves, so we can tell "untouched"
        # from "the user typed their own" and stop overwriting theirs.
        self._auto_name = ""

        self.var_target = tk.StringVar(value="__new__")
        self.var_provider = tk.StringVar(value="outlook")
        self.var_email = tk.StringVar()
        self.var_name = tk.StringVar()
        self.var_host = tk.StringVar()
        self.var_client_id = tk.StringVar(value=default_client_id())
        self.var_password = tk.StringVar()
        self.var_status = tk.StringVar()
        # Registered once for the window's lifetime: re-adding it every time the
        # account page is built would stack duplicate callbacks.
        self.var_email.trace_add("write", self._suggest_name)

        root.title(WINDOW_TITLE)
        root.minsize(600, 430)
        try:
            ttk.Style().theme_use("clam")
        except Exception:  # noqa: BLE001 - cosmetic only; any theme will do
            pass

        self._header = ttk.Label(root, text="", font=("TkDefaultFont", 15, "bold"))
        self._header.pack(anchor="w", padx=PAD, pady=(PAD, 0))
        self._subheader = ttk.Label(root, text="", wraplength=560, justify="left")
        self._subheader.pack(anchor="w", padx=PAD, pady=(2, PAD))

        self.body = ttk.Frame(root)
        self.body.pack(fill="both", expand=True, padx=PAD)

        ttk.Separator(root).pack(fill="x", pady=(PAD, 0))
        footer = ttk.Frame(root)
        footer.pack(fill="x", padx=PAD, pady=PAD)
        ttk.Label(footer, textvariable=self.var_status, wraplength=380, justify="left").pack(
            side="left"
        )
        self.btn_next = ttk.Button(footer, text="Next", command=self._on_next)
        self.btn_next.pack(side="right")
        self.btn_back = ttk.Button(footer, text="Back", command=self._on_back)
        self.btn_back.pack(side="right", padx=(0, 8))

        self._page = ""
        self.show_welcome()
        self.root.after(100, self._drain_events)

    # -- page plumbing ---------------------------------------------------
    def _reset_body(self, title: str, subtitle: str) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self._header.configure(text=title)
        self._subheader.configure(text=subtitle)
        self.var_status.set("")

    def _set_buttons(self, *, next_text: str, next_on: bool, back_on: bool) -> None:
        self.btn_next.configure(text=next_text, state="normal" if next_on else "disabled")
        self.btn_back.configure(state="normal" if back_on else "disabled")

    # -- page 1: welcome -------------------------------------------------
    def show_welcome(self) -> None:
        ttk = self._ttk
        self._page = "welcome"
        self._reset_body(
            "Set up your mail",
            "This connects one mailbox to Claude, so it can read your mail. "
            "It will ask a few questions, sign you in, and register the mail "
            "server with Claude Desktop and Claude Code if they are installed.",
        )
        if self._accounts:
            ttk.Label(self.body, text="What would you like to do?").pack(anchor="w", pady=(4, 6))
            ttk.Radiobutton(
                self.body,
                text="Add another mailbox",
                value="__new__",
                variable=self.var_target,
            ).pack(anchor="w")
            for name in sorted(self._accounts):
                account = self._accounts[name]
                ttk.Radiobutton(
                    self.body,
                    text=f"Sign in again / repair  —  {name} <{account.email}>",
                    value=name,
                    variable=self.var_target,
                ).pack(anchor="w")
        else:
            ttk.Label(
                self.body,
                text="Nothing is configured yet, so this will set up your first mailbox.",
                wraplength=560,
                justify="left",
            ).pack(anchor="w", pady=4)
        self._set_buttons(next_text="Next", next_on=True, back_on=False)

    # -- page 2: the account ---------------------------------------------
    def show_account(self) -> None:
        ttk = self._ttk
        self._page = "account"
        repairing = self.var_target.get() != "__new__"
        if repairing:
            plan = plan_from_existing(self._accounts[self.var_target.get()])
            self.var_provider.set(plan.provider)
            self.var_email.set(plan.email)
            self.var_name.set(plan.name)
            self.var_host.set(plan.host or "")
            self.var_client_id.set(default_client_id(plan.client_id))

        self._reset_body(
            "Your mailbox",
            "Outlook and Hotmail addresses sign in through Microsoft. Anything "
            "else (Gmail, Fastmail, iCloud, your own server) connects over IMAP "
            "with an app password.",
        )
        grid = ttk.Frame(self.body)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        ttk.Label(grid, text="Provider").grid(row=0, column=0, sticky="w", pady=4)
        choices = ttk.Frame(grid)
        choices.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            choices,
            text="Outlook / Hotmail",
            value="outlook",
            variable=self.var_provider,
            command=self._sync_provider_fields,
        ).pack(side="left")
        ttk.Radiobutton(
            choices,
            text="Other (IMAP)",
            value="generic",
            variable=self.var_provider,
            command=self._sync_provider_fields,
        ).pack(side="left", padx=(12, 0))

        ttk.Label(grid, text="Email address").grid(row=1, column=0, sticky="w", pady=4)
        email_entry = ttk.Entry(grid, textvariable=self.var_email)
        email_entry.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(grid, text="Name for this account").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(grid, textvariable=self.var_name).grid(row=2, column=1, sticky="ew", pady=4)

        self._row_host = ttk.Label(grid, text="IMAP server")
        self._host_box = ttk.Combobox(
            grid, textvariable=self.var_host, values=list(KNOWN_IMAP_HOSTS.values())
        )
        self._row_host.grid(row=3, column=0, sticky="w", pady=4)
        self._host_box.grid(row=3, column=1, sticky="ew", pady=4)

        self._row_client = ttk.Label(grid, text="Microsoft client ID")
        self._client_box = ttk.Entry(grid, textvariable=self.var_client_id)
        self._row_client.grid(row=4, column=0, sticky="w", pady=4)
        self._client_box.grid(row=4, column=1, sticky="ew", pady=4)

        self._hint = ttk.Label(
            self.body, text="", wraplength=560, justify="left", foreground="#555"
        )
        self._hint.pack(anchor="w", pady=(10, 0))

        self._sync_provider_fields()
        email_entry.focus_set()
        self._set_buttons(next_text="Next", next_on=True, back_on=True)

    def _sync_provider_fields(self) -> None:
        """Only show the field that the chosen provider actually needs."""
        outlook = self.var_provider.get() == "outlook"
        for widget, shown in (
            (self._row_host, not outlook),
            (self._host_box, not outlook),
            (self._row_client, outlook),
            (self._client_box, outlook),
        ):
            if shown:
                widget.grid()
            else:
                widget.grid_remove()
        self._hint.configure(
            text=(
                "The client ID above is the public one Thunderbird uses, so this "
                "works without registering anything with Microsoft yourself. The "
                "sign-in screen will say “Thunderbird”; that is expected. "
                "Paste your own Azure client ID instead if you have one."
            )
            if outlook
            else (
                "Gmail, iCloud and Yahoo need an app password created in your mail "
                "account's security settings — not your normal login password."
            )
        )

    def _suggest_name(self, *_args) -> None:
        """Fill the account name from the email until the user types their own."""
        if self._page != "account" or self.var_target.get() != "__new__":
            return
        if self.var_name.get() not in ("", self._auto_name):
            return  # they typed their own name; leave it alone
        email = self.var_email.get()
        self._auto_name = suggest_account_name(email, self._accounts) if "@" in email else ""
        self.var_name.set(self._auto_name)

    def _current_plan(self) -> SetupPlan:
        outlook = self.var_provider.get() == "outlook"
        base = SetupPlan(
            name=self.var_name.get().strip(),
            provider=self.var_provider.get(),
            email=self.var_email.get().strip(),
            host=None if outlook else self.var_host.get().strip(),
            client_id=self.var_client_id.get().strip() if outlook else None,
        )
        # Preserve anything hand-tuned on an account being repaired.
        if (name := self.var_target.get()) != "__new__" and name in self._accounts:
            existing = self._accounts[name]
            base.port, base.ssl = existing.port, existing.ssl
        return base

    # -- page 3: signing in ----------------------------------------------
    def show_signin(self) -> None:
        ttk = self._ttk
        self._page = "signin"
        plan = self._current_plan()
        if plan.provider == "outlook":
            self._reset_body(
                "Sign in to Microsoft",
                "A code will appear below. Open the sign-in page, enter the code, "
                "and approve access to your mail. This window will continue on its "
                "own once you are done.",
            )
            self._code_label = ttk.Label(self.body, text="…", font=("TkFixedFont", 22, "bold"))
            self._code_label.pack(anchor="w", pady=(8, 4))
            row = ttk.Frame(self.body)
            row.pack(anchor="w", pady=4)
            self._btn_copy = ttk.Button(
                row, text="Copy code", command=self._copy_code, state="disabled"
            )
            self._btn_copy.pack(side="left")
            self._btn_open = ttk.Button(
                row, text="Open sign-in page", command=self._open_verification, state="disabled"
            )
            self._btn_open.pack(side="left", padx=(8, 0))
            self._verification_url = ""
            self._device_code = ""
            self._set_buttons(next_text="Next", next_on=False, back_on=False)
            self.var_status.set("Contacting Microsoft…")
            self._start_worker(plan)
        else:
            self._reset_body(
                "App password",
                f"Enter the app password for {plan.email}. It is stored in your "
                "system's credential manager, not in any config file.",
            )
            entry = ttk.Entry(self.body, textvariable=self.var_password, show="*", width=32)
            entry.pack(anchor="w", pady=8)
            entry.focus_set()
            entry.bind("<Return>", lambda _e: self._on_next())
            self._set_buttons(next_text="Sign in", next_on=True, back_on=True)

    def _copy_code(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._device_code)
        self.var_status.set("Code copied to the clipboard.")

    def _open_verification(self) -> None:
        if self._verification_url:
            webbrowser.open(self._verification_url)

    # -- page 4: the result ----------------------------------------------
    def show_finish(self, result: SetupResult) -> None:
        tk, ttk = self._tk, self._ttk
        self._page = "finish"
        if result.signin_error:
            title = "Almost there"
            subtitle = "Your mailbox is configured, but signing in did not finish."
        else:
            title = "You're all set"
            subtitle = "Your mail is configured and connected to Claude."
        self._reset_body(title, subtitle)

        lines: list[str] = []
        if result.signin_message:
            lines.append(result.signin_message)
        if result.signin_error:
            lines.append(f"Sign-in problem: {result.signin_error}")
            lines.append("Run this setup again to retry the sign-in step.")
        lines.append("")
        lines.append(f"Config:  {result.config_file}")
        lines.append(f"Secrets: {result.secret_backend}")
        if result.server_path:
            lines.append(f"Server:  {result.server_path}")
        lines.extend(result.notes)

        wrapper = ttk.Frame(self.body)
        wrapper.pack(fill="both", expand=True)
        text = tk.Text(wrapper, wrap="word", height=11, relief="flat", background="#f4f4f4")
        scroll = ttk.Scrollbar(wrapper, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")

        self.exit_code = 0 if result.ok else 1
        self._set_buttons(next_text="Close", next_on=True, back_on=False)

    # -- navigation ------------------------------------------------------
    def _on_next(self) -> None:
        if self._page == "welcome":
            self.show_account()
        elif self._page == "account":
            if problem := validate_plan(self._current_plan()):
                self.var_status.set(problem)
                return
            self.show_signin()
        elif self._page == "signin":
            # Only reachable on the password page; the device-code page drives
            # itself and keeps Next disabled until the worker is done.
            self._password = self.var_password.get()
            if not self._password.strip():
                self.var_status.set("Enter the app password to continue.")
                return
            self.var_status.set("Signing in…")
            self._set_buttons(next_text="Sign in", next_on=False, back_on=False)
            self._start_worker(self._current_plan())
        elif self._page == "finish":
            self.root.destroy()

    def _on_back(self) -> None:
        if self._page == "account":
            self.show_welcome()
        elif self._page == "signin":
            self.show_account()

    # -- worker + event pump ---------------------------------------------
    def _start_worker(self, plan: SetupPlan) -> None:
        def work() -> None:
            try:
                result = apply_setup(
                    plan,
                    config_file=self.config_file,
                    install_dir=self.install_dir,
                    ui=self,
                )
                self._events.put(("done", result))
            except Exception as exc:  # noqa: BLE001 - surfaced on the page
                self._events.put(("failed", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "device_code":
                    self._show_device_code(payload)  # type: ignore[arg-type]
                elif kind == "done":
                    self.show_finish(payload)  # type: ignore[arg-type]
                elif kind == "failed":
                    # Only the config write raises this far; everything after it
                    # is reported on the finish page. Let them fix and retry.
                    self.var_status.set(str(payload))
                    self._set_buttons(next_text="Try again", next_on=True, back_on=True)
        except queue.Empty:
            pass
        # The window is gone once the user closes the final page, and
        # rescheduling against a destroyed root is an error rather than a no-op.
        if self.root.winfo_exists():
            self.root.after(100, self._drain_events)

    def _show_device_code(self, flow: dict) -> None:
        self._device_code = str(flow.get("user_code", ""))
        self._verification_url = str(flow.get("verification_uri", ""))
        self._code_label.configure(text=self._device_code or "?")
        self._btn_copy.configure(state="normal")
        self._btn_open.configure(state="normal")
        self.var_status.set("Waiting for you to approve the sign-in…")
        if self._verification_url:
            webbrowser.open(self._verification_url)

    # -- AuthUI, called on the worker thread -----------------------------
    def device_code(self, flow: dict) -> None:
        self._events.put(("device_code", flow))

    def ask_password(self, account: Account) -> str:
        # Already collected on the sign-in page: the worker must never block
        # waiting for the UI thread, which is busy pumping events for it.
        return self._password


def run(
    *,
    config_file: Path | None = None,
    install_dir: Path | None = None,
    force_console: bool = False,
) -> int:
    """Open the setup window, falling back to the console wizard if it can't.

    A missing display (SSH, a headless box) or a Python built without Tk are
    both ordinary situations rather than errors, so setup keeps working in the
    terminal instead of refusing to start.
    """
    if not force_console:
        try:
            import tkinter as tk

            root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - ImportError or TclError
            print(f"No graphical display available ({exc}); continuing in the terminal.")
        else:
            wizard = Wizard(root, config_file=config_file, install_dir=install_dir)
            root.mainloop()
            return wizard.exit_code

    return console_wizard(config_file=config_file, install_dir=install_dir)
