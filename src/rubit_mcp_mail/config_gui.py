"""The settings window: a Tk front end over config.toml.

This is what the installed `rubit-mcp-mail-gui` executable opens, and what
`rubit-mcp-mail gui` opens from a terminal. It replaces an earlier local web
GUI - the point of the change is that a non-technical user reaches their
settings by clicking a shortcut, never by typing a command or trusting a URL.

Dropping the HTTP server dropped a whole security layer with it: there is no
port to bind, no access token to carry, and no browser tab that another site
could post into. A window can only be driven by the person at the machine.

Layout mirrors what the web pages did: four tabs (Accounts, Permissions,
Providers, Doctor), with add/edit/sign-in opening a modal dialog. Every write
goes through `config_editor`, so the file keeps its comments and is never left
in a state the CLI would refuse to load.

Threading rule, the same one `installer_gui` follows because tkinter has no
tolerance for breaking it: blocking work (IMAP, MSAL, the keyring) runs on a
worker thread which only ever posts onto a queue, and widgets are touched
exclusively from the drain loop on the main thread. `BackgroundWork` below is
that rule in one place.

Nothing here is imported at module scope by anything else, and tkinter is
imported inside the functions that need it, so a Python built without Tk fails
with a clear message rather than an ImportError traceback.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__
from .auth import MicrosoftDeviceCodeAuth, PasswordAuth
from .config import Account, config_path
from .config_editor import (
    disabled_from_enabled,
    load_document,
    remove_account,
    remove_provider_override,
    save_document,
    set_download_dir,
    upsert_account,
    upsert_provider_override,
    validate_account_form,
    write_disabled_tools,
)
from .diagnostics import AccountReport, Report, run_doctor
from .permissions import TOOL_LABELS, TOOL_NAMES
from .providers import PROFILES, THUNDERBIRD_CLIENT_ID
from .secrets import SecretStore
from .session import Session

WINDOW_TITLE = "rubit-mcp-mail Settings"
PAD = 12

PROVIDER_LABELS = {"outlook": "Outlook.com / Microsoft 365", "generic": "Other IMAP server"}

#: Tab names, in order. `run(page=...)` takes one of these.
PAGES = ("accounts", "permissions", "providers", "doctor")


# -- pure helpers, so the logic can be tested without a display --------------
def raw_accounts(doc: Any) -> dict[str, dict]:
    """Account tables straight from the TOML, bypassing validation.

    The forms are built from these rather than from `Config` so that an account
    which fails validation - the exact case a user needs help with - can still
    be opened and repaired.
    """
    accounts = doc.get("accounts") or {}
    return {name: dict(body) for name, body in accounts.items()}


def auth_label(report: AccountReport) -> str:
    """Short sign-in state for the accounts list."""
    if report.error and not report.auth_state:
        return "config error"
    state = report.auth_state or "error"
    return {"ok": "signed in", "needs_auth": "not signed in"}.get(state, state)


def summarise(detail: str, limit: int = 90) -> str:
    """First sentence of a diagnosis, clipped to fit a table cell."""
    summary = detail.split(". ")[0]
    if len(summary) > limit:
        return summary[:limit].rsplit(" ", 1)[0] + "..."
    return summary + "..." if summary != detail else summary


def account_rows(report: Report, raw: dict[str, dict]) -> list[tuple[str, ...]]:
    """(name, email, provider, server, state, detail) per account, for the list.

    When the config file does not load at all, `report.accounts` is empty and
    every account is listed from the raw TOML instead - that is the case where
    the user most needs to open one and fix it.
    """
    rows: list[tuple[str, ...]] = []
    for account in report.accounts:
        detail = account.auth_detail or account.error or ""
        server = f"{account.host or ''}:{account.port}" if account.host else ""
        rows.append(
            (
                account.name,
                account.email,
                account.provider,
                server,
                auth_label(account),
                summarise(detail),
            )
        )
    if report.config_error:
        for name in sorted(raw):
            body = raw[name]
            rows.append(
                (
                    name,
                    str(body.get("email", "")),
                    str(body.get("provider", "generic")),
                    str(body.get("host", "")),
                    "not loaded",
                    "",
                )
            )
    return rows


def parse_provider_form(values: dict[str, str], scopes_text: str) -> dict[str, Any]:
    """Normalise one provider-override form into `upsert_provider_override` fields.

    Raises ValueError with a message meant for the user. Whether a key is
    actually overridable is not re-checked here: `save_document` runs
    `load_config`, which applies the overrides and rejects the unknown ones.
    """
    port = values.get("port", "").strip()
    ssl = values.get("ssl", "").strip().lower()

    fields: dict[str, Any] = {
        "host": values.get("host", "").strip(),
        "port": "",
        "ssl": "",
        "authority": values.get("authority", "").strip(),
        "scopes": [line.strip() for line in scopes_text.splitlines() if line.strip()],
    }
    if port:
        try:
            fields["port"] = int(port)
        except ValueError:
            raise ValueError(f"Port must be a whole number, not {port!r}.") from None
    if ssl:
        if ssl not in ("true", "false"):
            raise ValueError(f"SSL must be 'true' or 'false', not {ssl!r}.")
        fields["ssl"] = ssl == "true"
    return fields


def doctor_text(report: Report) -> str:
    """The doctor result as plain text, the same diagnosis the CLI prints."""
    lines = [
        f"Version:   {report.version}",
        f"Config:    {report.config_path}",
        f"Downloads: {report.download_dir}",
        f"Secrets:   {report.secrets_backend}",
        "",
    ]
    if report.config_error:
        lines.append(f"This config file does not load: {report.config_error}")
        return "\n".join(lines)
    if not report.accounts:
        lines.append("No accounts configured.")
        return "\n".join(lines)

    lines.append(
        f"{report.failures} account(s) not working." if report.failures else "All accounts OK."
    )
    for account in report.accounts:
        lines.append("")
        lines.append(f"=== {account.name} — {auth_label(account)}")
        if account.error and not account.auth_state:
            lines.append(f"  {account.error}")
            continue
        lines.append(
            f"  {account.provider}  {account.host}:{account.port} "
            f"ssl={account.ssl}  {account.email}"
        )
        if account.auth_state != "ok":
            lines.append(f"  {account.auth_detail or 'not signed in'}")
            continue
        if account.error:
            lines.append(f"  {account.error}")
            continue
        if not account.connected:
            lines.append("  Credential found. No connection was attempted.")
            continue
        lines.append(f"  capabilities: {' '.join(account.capabilities[:12])}")
        lines.append(f"  {len(account.folders)} folders found")
        for folder in account.folders:
            counts = (
                f"{folder.messages:>6} msgs, {folder.unseen or 0} unread"
                if folder.messages is not None
                else ""
            )
            lines.append(f"    [{folder.role:<7}] {folder.name:<28} {counts}")
    return "\n".join(lines)


# -- the threading rule, in one place ----------------------------------------
class BackgroundWork:
    """Run blocking work off the UI thread and deliver the result on it.

    `start` takes a callable run on a worker thread; whatever it returns is
    posted as ("done", value), and an exception as ("failed", message). The
    handlers registered with `on` run on the main thread, so they - and only
    they - may touch widgets.
    """

    def __init__(self, widget: Any) -> None:
        self._widget = widget
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._handlers: dict[str, Callable[[Any], None]] = {}
        widget.after(100, self._drain)

    def on(self, kind: str, handler: Callable[[Any], None]) -> None:
        self._handlers[kind] = handler

    def post(self, kind: str, payload: object = None) -> None:
        """Hand something to the main thread. Safe to call from a worker."""
        self._events.put((kind, payload))

    def start(self, work: Callable[[], Any]) -> None:
        def run() -> None:
            try:
                self.post("done", work())
            except Exception as exc:  # noqa: BLE001 - surfaced on the page
                self.post("failed", str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if handler := self._handlers.get(kind):
                    handler(payload)
        except queue.Empty:
            pass
        # The widget is gone once its window closes, and rescheduling against a
        # destroyed one is an error rather than a no-op.
        if self._widget.winfo_exists():
            self._widget.after(100, self._drain)


# -- dialogs -----------------------------------------------------------------
class AccountDialog:
    """Add or edit one `[accounts.<name>]` table."""

    def __init__(self, parent: Any, path: Path, name: str | None) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk, self._ttk = tk, ttk
        self.path = path
        self.name = name
        self.is_new = name is None
        self.saved = False

        doc = load_document(path)
        existing = raw_accounts(doc)
        fields = dict(existing.get(name or "", {})) if not self.is_new else {"provider": "outlook"}

        self.top = tk.Toplevel(parent)
        self.top.title("Add an account" if self.is_new else f"Account: {name}")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.minsize(560, 400)

        self.var_name = tk.StringVar(value=name or "")
        self.var_provider = tk.StringVar(value=str(fields.get("provider") or "generic"))
        self.var_email = tk.StringVar(value=str(fields.get("email") or ""))
        self.var_client_id = tk.StringVar(value=str(fields.get("client_id") or ""))
        self.var_host = tk.StringVar(value=str(fields.get("host") or ""))
        self.var_port = tk.StringVar(value=str(fields.get("port") or ""))
        self.var_ssl = tk.StringVar(value=_ssl_choice(fields.get("ssl")))
        self.var_status = tk.StringVar()

        body = ttk.Frame(self.top, padding=PAD)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="Account name").grid(row=0, column=0, sticky="w", pady=4)
        if self.is_new:
            ttk.Entry(body, textvariable=self.var_name).grid(row=0, column=1, sticky="ew", pady=4)
            ttk.Label(
                body,
                text="Short handle you will use in Claude, e.g. 'work'. Letters, digits, . - _",
                foreground="#555",
                wraplength=380,
            ).grid(row=1, column=1, sticky="w")
        else:
            ttk.Entry(body, textvariable=self.var_name, state="disabled").grid(
                row=0, column=1, sticky="ew", pady=4
            )
            ttk.Label(
                body,
                text=(
                    "Renaming would orphan the stored credential. To rename, add a "
                    "new account and remove this one."
                ),
                foreground="#555",
                wraplength=380,
            ).grid(row=1, column=1, sticky="w")

        ttk.Label(body, text="Provider").grid(row=2, column=0, sticky="w", pady=4)
        provider_box = ttk.Combobox(
            body,
            textvariable=self.var_provider,
            state="readonly",
            values=[PROVIDER_LABELS.get(key, key) for key in sorted(PROFILES)],
        )
        provider_box.grid(row=2, column=1, sticky="ew", pady=4)
        provider_box.set(PROVIDER_LABELS.get(self.var_provider.get(), self.var_provider.get()))
        provider_box.bind("<<ComboboxSelected>>", self._on_provider_change)
        self._provider_box = provider_box

        ttk.Label(body, text="Email address").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=self.var_email).grid(row=3, column=1, sticky="ew", pady=4)

        # One frame per provider, shown and hidden by the combobox above. This
        # is what the web form did with a scrap of JavaScript.
        self._outlook = ttk.LabelFrame(body, text="Outlook sign-in", padding=PAD)
        self._outlook.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._outlook.columnconfigure(1, weight=1)
        ttk.Label(self._outlook, text="Client ID").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(self._outlook, textvariable=self.var_client_id).grid(
            row=0, column=1, sticky="ew", pady=4
        )
        ttk.Button(self._outlook, text="Use Thunderbird's", command=self._use_thunderbird).grid(
            row=1, column=1, sticky="w"
        )
        ttk.Label(
            self._outlook,
            text=(
                "From your Azure app registration. No Azure app? Thunderbird's public "
                "client ID works without registering one — the Microsoft consent screen "
                "will then say “Thunderbird”."
            ),
            foreground="#555",
            wraplength=460,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._imap = ttk.LabelFrame(body, text="IMAP server", padding=PAD)
        self._imap.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._imap.columnconfigure(1, weight=1)
        ttk.Label(self._imap, text="Host").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(self._imap, textvariable=self.var_host).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(self._imap, text="Port").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(self._imap, textvariable=self.var_port, width=10).grid(
            row=1, column=1, sticky="w", pady=4
        )
        ttk.Label(self._imap, text="SSL/TLS").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(
            self._imap,
            textvariable=self.var_ssl,
            state="readonly",
            values=list(_SSL_CHOICES),
            width=24,
        ).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(
            self._imap,
            text="Leave port empty for 993. Only change SSL for a server without implicit TLS.",
            foreground="#555",
            wraplength=460,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Per-account tool permissions, on the edit form only: a brand new
        # account has nothing to forbid yet.
        self.tool_vars: dict[str, Any] = {}
        if not self.is_new:
            disabled = list(fields.get("disabled_tools") or [])
            tools = ttk.LabelFrame(body, text="Allowed tools", padding=PAD)
            tools.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 0))
            for index, tool in enumerate(TOOL_NAMES):
                var = tk.BooleanVar(value=tool not in disabled)
                self.tool_vars[tool] = var
                ttk.Checkbutton(tools, text=TOOL_LABELS[tool], variable=var).grid(
                    row=index // 2, column=index % 2, sticky="w", padx=(0, 16)
                )

        ttk.Label(
            body, textvariable=self.var_status, foreground="#a33", wraplength=520, justify="left"
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(PAD, 0))
        ttk.Button(buttons, text="Cancel", command=self.top.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self._save).pack(side="right", padx=(0, 8))

        self._sync_provider_frames()

    def _provider_key(self) -> str:
        """The combobox shows labels; the config stores keys."""
        shown = self._provider_box.get()
        for key, label in PROVIDER_LABELS.items():
            if label == shown:
                return key
        return shown

    def _on_provider_change(self, _event: Any = None) -> None:
        self._sync_provider_frames()

    def _sync_provider_frames(self) -> None:
        outlook = self._provider_key() == "outlook"
        for frame, shown in ((self._outlook, outlook), (self._imap, not outlook)):
            if shown:
                frame.grid()
            else:
                frame.grid_remove()

    def _use_thunderbird(self) -> None:
        self.var_client_id.set(THUNDERBIRD_CLIENT_ID)

    def _save(self) -> None:
        name = self.var_name.get().strip() if self.is_new else (self.name or "")
        doc = load_document(self.path)
        existing = raw_accounts(doc)
        try:
            if self.is_new and name in existing:
                raise ValueError(f"An account named {name!r} already exists.")
            cleaned = validate_account_form(
                name,
                {
                    "provider": self._provider_key(),
                    "email": self.var_email.get(),
                    "client_id": self.var_client_id.get(),
                    "host": self.var_host.get(),
                    "port": self.var_port.get(),
                    "ssl": _SSL_CHOICES[self.var_ssl.get()],
                },
            )
            upsert_account(doc, name, cleaned)
            if self.tool_vars:
                enabled = [tool for tool, var in self.tool_vars.items() if var.get()]
                table = doc["accounts"][name]
                if disabled := disabled_from_enabled(enabled):
                    table["disabled_tools"] = disabled
                else:
                    table.pop("disabled_tools", None)
            save_document(self.path, doc)
        except ValueError as exc:
            self.var_status.set(str(exc))
            return
        self.saved = True
        self.top.destroy()


class SignInDialog:
    """Run an account's real sign-in flow, whichever kind it is."""

    def __init__(self, parent: Any, name: str) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk, self._ttk = tk, ttk
        self.name = name
        self.done_message = ""

        self.top = tk.Toplevel(parent)
        self.top.title(f"Sign in: {name}")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.minsize(520, 300)

        self.var_password = tk.StringVar()
        self.var_status = tk.StringVar()
        self._device_code = ""
        self._verification_url = ""

        self.body = ttk.Frame(self.top, padding=PAD)
        self.body.pack(fill="both", expand=True)

        self.work = BackgroundWork(self.top)
        self.work.on("device_code", self._show_device_code)
        self.work.on("done", self._show_done)
        self.work.on("failed", self._show_failed)

        try:
            session = Session()
            account = session.account(name)
            self.strategy = session.auth_for(account)
        except Exception as exc:  # noqa: BLE001 - an unloadable account is a finding
            self._message("Cannot sign in", str(exc))
            return

        if isinstance(self.strategy, PasswordAuth):
            self._ask_password(account)
        elif isinstance(self.strategy, MicrosoftDeviceCodeAuth):
            self._start_device_flow(account)
        else:
            self._message(
                "Cannot sign in", f"No sign-in flow for the {account.provider!r} provider yet."
            )

    # -- pages -----------------------------------------------------------
    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

    def _message(self, title: str, detail: str) -> None:
        ttk = self._ttk
        self._clear()
        ttk.Label(self.body, text=title, font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(self.body, text=detail, wraplength=460, justify="left").pack(
            anchor="w", pady=(6, 0)
        )
        ttk.Button(self.body, text="Close", command=self.top.destroy).pack(
            anchor="e", pady=(PAD, 0)
        )

    def _ask_password(self, account: Account) -> None:
        ttk = self._ttk
        self._clear()
        ttk.Label(
            self.body, text=f"App password for {account.name}", font=("TkDefaultFont", 13, "bold")
        ).pack(anchor="w")
        ttk.Label(
            self.body,
            text=(
                f"{account.email} on {account.profile.host}:{account.profile.port}\n\n"
                "This is an app password created in your mail account's security "
                "settings, not your normal login password. It is stored in your "
                "system's credential manager — never in the config file."
            ),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        entry = ttk.Entry(self.body, textvariable=self.var_password, show="*", width=36)
        entry.pack(anchor="w", pady=PAD)
        entry.focus_set()
        entry.bind("<Return>", lambda _e: self._store_password())

        ttk.Label(self.body, textvariable=self.var_status, foreground="#a33", wraplength=460).pack(
            anchor="w"
        )
        buttons = ttk.Frame(self.body)
        buttons.pack(anchor="e", pady=(PAD, 0))
        ttk.Button(buttons, text="Cancel", command=self.top.destroy).pack(side="right")
        ttk.Button(buttons, text="Save password", command=self._store_password).pack(
            side="right", padx=(0, 8)
        )

    def _store_password(self) -> None:
        password = self.var_password.get()
        if not password.strip():
            self.var_status.set("Enter the app password to continue.")
            return
        self.var_status.set("Storing…")
        strategy = self.strategy
        assert isinstance(strategy, PasswordAuth)
        self.work.start(lambda: strategy.store_password(password))

    def _start_device_flow(self, account: Account) -> None:
        ttk = self._ttk
        self._clear()
        ttk.Label(
            self.body,
            text=f"Sign in to Microsoft: {account.name}",
            font=("TkDefaultFont", 13, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self.body,
            text=(
                "A code will appear below. Open the sign-in page, enter the code, and "
                "approve access to your mail. This window continues on its own once "
                "you are done."
            ),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        self._code_label = ttk.Label(self.body, text="…", font=("TkFixedFont", 22, "bold"))
        self._code_label.pack(anchor="w", pady=(10, 4))
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
        ttk.Label(self.body, textvariable=self.var_status, wraplength=460, justify="left").pack(
            anchor="w", pady=(10, 0)
        )
        self.var_status.set("Contacting Microsoft…")

        # `interactive_setup` blocks for the whole handshake and calls back with
        # the code through the AuthUI protocol - which is exactly what a worker
        # thread can do, so there is no need to drive begin/complete by hand.
        strategy = self.strategy
        self.work.start(lambda: strategy.interactive_setup(self))

    def _copy_code(self) -> None:
        self.top.clipboard_clear()
        self.top.clipboard_append(self._device_code)
        self.var_status.set("Code copied to the clipboard.")

    def _open_verification(self) -> None:
        # A browser is right here: this is Microsoft's sign-in page, not our UI.
        if self._verification_url:
            webbrowser.open(self._verification_url)

    # -- worker results, on the main thread ------------------------------
    def _show_device_code(self, flow: Any) -> None:
        self._device_code = str(flow.get("user_code", ""))
        self._verification_url = str(flow.get("verification_uri", ""))
        self._code_label.configure(text=self._device_code or "?")
        self._btn_copy.configure(state="normal")
        self._btn_open.configure(state="normal")
        self.var_status.set("Waiting for you to approve the sign-in…")
        if self._verification_url:
            webbrowser.open(self._verification_url)

    def _show_done(self, message: Any) -> None:
        self.done_message = str(message)
        self._message("Signed in", str(message))

    def _show_failed(self, message: Any) -> None:
        self._message("Sign-in did not finish", str(message))

    # -- AuthUI, called on the worker thread -----------------------------
    def device_code(self, flow: dict) -> None:
        self.work.post("device_code", flow)

    def ask_password(self, account: Account) -> str:
        # Only reached for password providers, which this dialog handles with
        # `store_password` instead - the worker must never block on the UI.
        return self.var_password.get()


#: Label shown in the SSL dropdown -> what `validate_account_form` expects.
_SSL_CHOICES = {"Provider default": "", "On": "true", "Off (plaintext)": "false"}


def _ssl_choice(value: Any) -> str:
    """Which SSL dropdown label a stored value corresponds to."""
    if value is None or value == "":
        return "Provider default"
    return "On" if value is True or str(value).lower() == "true" else "Off (plaintext)"


# -- the window --------------------------------------------------------------
class ConfigWindow:
    """Four tabs over one config file."""

    def __init__(self, root: Any, *, page: str = "accounts") -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk, self._ttk = tk, ttk
        self.root = root
        self.path = config_path()

        root.title(f"{WINDOW_TITLE} — v{__version__}")
        root.minsize(760, 560)
        try:
            ttk.Style().theme_use("clam")
        except Exception:  # noqa: BLE001 - cosmetic only; any theme will do
            pass

        self.var_status = tk.StringVar()
        self.var_download_dir = tk.StringVar()

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=PAD, pady=(PAD, 0))

        self.tab_accounts = ttk.Frame(self.notebook, padding=PAD)
        self.tab_permissions = ttk.Frame(self.notebook, padding=PAD)
        self.tab_providers = ttk.Frame(self.notebook, padding=PAD)
        self.tab_doctor = ttk.Frame(self.notebook, padding=PAD)
        for frame, title in (
            (self.tab_accounts, "Accounts"),
            (self.tab_permissions, "Permissions"),
            (self.tab_providers, "Providers"),
            (self.tab_doctor, "Doctor"),
        ):
            self.notebook.add(frame, text=title)

        ttk.Separator(root).pack(fill="x", pady=(PAD, 0))
        ttk.Label(root, textvariable=self.var_status, wraplength=720, justify="left").pack(
            anchor="w", padx=PAD, pady=(6, PAD)
        )

        # Running doctor is the only blocking work this window does itself;
        # both outcomes render into the same pane.
        self.work = BackgroundWork(root)
        self.work.on("done", self._show_doctor_result)
        self.work.on("failed", self._show_doctor_result)

        self._build_accounts()
        self._build_permissions()
        self._build_providers()
        self._build_doctor()
        self.refresh()

        if page in PAGES:
            self.notebook.select(PAGES.index(page))

    def refresh(self) -> None:
        """Re-read the config file and rebuild every tab from it."""
        self._refresh_accounts()
        self._refresh_permissions()
        self._refresh_providers()

    # -- accounts tab ----------------------------------------------------
    def _build_accounts(self) -> None:
        ttk = self._ttk
        frame = self.tab_accounts
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        self.lbl_paths = ttk.Label(frame, text="", foreground="#555", justify="left")
        self.lbl_paths.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        columns = ("email", "provider", "server", "state", "detail")
        tree = ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="browse")
        tree.heading("#0", text="Account")
        tree.column("#0", width=120, stretch=False)
        for column, title, width in (
            ("email", "Email", 190),
            ("provider", "Provider", 90),
            ("server", "Server", 160),
            ("state", "Sign-in", 110),
            ("detail", "Detail", 200),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width, stretch=(column == "detail"))
        tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.grid(row=1, column=1, sticky="ns")
        tree.bind("<Double-1>", lambda _e: self._edit_account())
        self.tree = tree

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        for text, command in (
            ("Add an account", self._add_account),
            ("Edit", self._edit_account),
            ("Sign in", self._sign_in),
            ("Remove", self._remove_account),
        ):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 8))

        downloads = ttk.LabelFrame(frame, text="Attachment downloads", padding=PAD)
        downloads.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        downloads.columnconfigure(0, weight=1)
        ttk.Entry(downloads, textvariable=self.var_download_dir).grid(row=0, column=0, sticky="ew")
        ttk.Button(downloads, text="Save", command=self._save_download_dir).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Label(
            downloads,
            text=(
                "Where get_attachment saves files; empty means the default. A running "
                "MCP server reads its config once at startup, so restart Claude Desktop "
                "for changes here to take effect."
            ),
            foreground="#555",
            wraplength=640,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _refresh_accounts(self) -> None:
        # connect=False: this list must stay instant, so it checks credentials
        # only. The Doctor tab is where the network gets touched.
        report = run_doctor(connect=False)
        doc = load_document(self.path)
        rows = account_rows(report, raw_accounts(doc))

        self.tree.delete(*self.tree.get_children())
        for name, email, provider, server, state, detail in rows:
            self.tree.insert(
                "", "end", iid=name, text=name, values=(email, provider, server, state, detail)
            )

        self.var_download_dir.set(str(doc.get("download_dir") or ""))
        lines = [f"Config: {report.config_path}", f"Secrets: {report.secrets_backend}"]
        if report.provider_overrides:
            listed = "; ".join(
                f"{name} ({', '.join(keys)})" for name, keys in report.provider_overrides.items()
            )
            lines.append(f"Provider overrides in effect: {listed}")
        if report.secrets_warning:
            lines.append(
                "Credentials in the OS keyring are not readable from this process, so "
                "anything signed in elsewhere will look signed out here."
            )
        self.lbl_paths.configure(text="\n".join(lines))

        if report.missing_config:
            self.var_status.set(
                f"No config file yet at {report.config_path}. "
                "Add an account and one will be written."
            )
        elif report.config_error:
            self.var_status.set(f"This config file does not load: {report.config_error}")
        elif not rows:
            self.var_status.set("No accounts configured yet. Add one to get started.")
        else:
            self.var_status.set("")

    def _selected(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            self.var_status.set("Select an account in the list first.")
            return None
        return str(selection[0])

    def _add_account(self) -> None:
        dialog = AccountDialog(self.root, self.path, None)
        self.root.wait_window(dialog.top)
        if dialog.saved:
            self.refresh()
            self.var_status.set("Account saved.")

    def _edit_account(self) -> None:
        if name := self._selected():
            dialog = AccountDialog(self.root, self.path, name)
            self.root.wait_window(dialog.top)
            if dialog.saved:
                self.refresh()
                self.var_status.set(f"Saved {name}.")

    def _sign_in(self) -> None:
        if name := self._selected():
            dialog = SignInDialog(self.root, name)
            self.root.wait_window(dialog.top)
            self.refresh()
            if dialog.done_message:
                self.var_status.set(dialog.done_message)

    def _remove_account(self) -> None:
        from tkinter import messagebox

        name = self._selected()
        if not name:
            return
        store = SecretStore()
        keys = [f"password:{name}", f"msal-cache:{name}"]
        has_secret = any(store.get(key) for key in keys)

        question = (
            f"Remove the account {name!r} from your config file?\n\n"
            "Nothing in your mailbox is touched."
        )
        if has_secret:
            question += "\n\nIts stored credential will be deleted too."
        if not messagebox.askyesno("Remove account", question, parent=self.root):
            return

        doc = load_document(self.path)
        remove_account(doc, name)
        try:
            save_document(self.path, doc)
        except ValueError as exc:
            self.var_status.set(str(exc))
            return
        if has_secret:
            for key in keys:
                store.delete(key)
        self.refresh()
        self.var_status.set(f"Removed {name}.")

    def _save_download_dir(self) -> None:
        doc = load_document(self.path)
        set_download_dir(doc, self.var_download_dir.get())
        try:
            save_document(self.path, doc)
        except ValueError as exc:
            self.var_status.set(str(exc))
            return
        self.refresh()
        self.var_status.set("Download directory saved.")

    # -- permissions tab -------------------------------------------------
    def _build_permissions(self) -> None:
        ttk = self._ttk
        frame = self.tab_permissions
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text=(
                "Untick a tool to forbid it for that account. A blocked call returns a "
                "plain error to the model. Restart the MCP server for changes to take "
                "effect."
            ),
            wraplength=680,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        self._permissions_grid = ttk.Frame(frame)
        self._permissions_grid.grid(row=1, column=0, sticky="nsew", pady=PAD)
        ttk.Button(frame, text="Save permissions", command=self._save_permissions).grid(
            row=2, column=0, sticky="w"
        )
        self.permission_vars: dict[str, dict[str, Any]] = {}

    def _refresh_permissions(self) -> None:
        tk, ttk = self._tk, self._ttk
        grid = self._permissions_grid
        for child in grid.winfo_children():
            child.destroy()
        self.permission_vars = {}

        accounts = raw_accounts(load_document(self.path))
        if not accounts:
            ttk.Label(grid, text="No accounts configured.").grid(row=0, column=0, sticky="w")
            return

        ttk.Label(grid, text="Account", font=("TkDefaultFont", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 16)
        )
        for column, tool in enumerate(TOOL_NAMES, start=1):
            ttk.Label(grid, text=TOOL_LABELS[tool], font=("TkDefaultFont", 9, "bold")).grid(
                row=0, column=column, sticky="w", padx=(0, 12)
            )

        for row, name in enumerate(sorted(accounts), start=1):
            disabled = list(accounts[name].get("disabled_tools") or [])
            ttk.Label(grid, text=name).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=3)
            self.permission_vars[name] = {}
            for column, tool in enumerate(TOOL_NAMES, start=1):
                var = tk.BooleanVar(value=tool not in disabled)
                self.permission_vars[name][tool] = var
                ttk.Checkbutton(grid, variable=var).grid(row=row, column=column, pady=3)

    def _save_permissions(self) -> None:
        updates = {
            name: disabled_from_enabled([tool for tool, var in tools.items() if var.get()])
            for name, tools in self.permission_vars.items()
        }
        try:
            write_disabled_tools(self.path, updates)
        except ValueError as exc:
            self.var_status.set(str(exc))
            return
        self.refresh()
        self.var_status.set("Permissions saved. Restart the MCP server for them to take effect.")

    # -- providers tab ---------------------------------------------------
    def _build_providers(self) -> None:
        ttk = self._ttk
        frame = self.tab_providers
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(
            frame,
            text=(
                "The IMAP hosts and OAuth endpoints are compiled into this release. If a "
                "provider changes one, correct it here and it takes effect immediately — "
                "no new release needed. Leave a field empty to keep the built-in value."
            ),
            wraplength=680,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        self._providers_box = ttk.Frame(frame)
        self._providers_box.grid(row=1, column=0, sticky="nsew", pady=PAD)
        ttk.Button(frame, text="Save overrides", command=self._save_providers).grid(
            row=2, column=0, sticky="w"
        )
        self.provider_vars: dict[str, dict[str, Any]] = {}
        self.provider_scopes: dict[str, Any] = {}

    def _refresh_providers(self) -> None:
        tk, ttk = self._tk, self._ttk
        box = self._providers_box
        for child in box.winfo_children():
            child.destroy()
        box.columnconfigure(0, weight=1)
        self.provider_vars = {}
        self.provider_scopes = {}

        doc = load_document(self.path)
        overrides = {name: dict(body) for name, body in (doc.get("providers") or {}).items()}

        for index, provider in enumerate(sorted(PROFILES)):
            profile = PROFILES[provider]
            current = overrides.get(provider, {})
            oauth = current.get("oauth", {}) if isinstance(current.get("oauth"), dict) else {}

            label = PROVIDER_LABELS.get(provider, provider)
            group = ttk.LabelFrame(box, text=f"{label}  ({provider})", padding=PAD)
            group.grid(row=index, column=0, sticky="ew", pady=(0, PAD))
            group.columnconfigure(1, weight=1)

            variables = {
                "host": tk.StringVar(value=str(current.get("host", ""))),
                "port": tk.StringVar(value=str(current.get("port", ""))),
                "ssl": tk.StringVar(value=_ssl_choice(current.get("ssl"))),
                "authority": tk.StringVar(value=str(oauth.get("authority", ""))),
            }
            self.provider_vars[provider] = variables

            ttk.Label(group, text="IMAP host").grid(row=0, column=0, sticky="w", pady=3)
            ttk.Entry(group, textvariable=variables["host"]).grid(
                row=0, column=1, sticky="ew", pady=3
            )
            ttk.Label(
                group, text=f"Built in: {profile.host or '(set per account)'}", foreground="#555"
            ).grid(row=1, column=1, sticky="w")

            ttk.Label(group, text="Port").grid(row=2, column=0, sticky="w", pady=3)
            ttk.Entry(group, textvariable=variables["port"], width=10).grid(
                row=2, column=1, sticky="w", pady=3
            )
            ttk.Label(group, text=f"Built in: {profile.port}", foreground="#555").grid(
                row=3, column=1, sticky="w"
            )

            ttk.Label(group, text="SSL").grid(row=4, column=0, sticky="w", pady=3)
            ttk.Combobox(
                group,
                textvariable=variables["ssl"],
                state="readonly",
                values=list(_SSL_CHOICES),
                width=24,
            ).grid(row=4, column=1, sticky="w", pady=3)

            if profile.oauth is not None:
                ttk.Label(group, text="OAuth authority").grid(row=5, column=0, sticky="w", pady=3)
                ttk.Entry(group, textvariable=variables["authority"]).grid(
                    row=5, column=1, sticky="ew", pady=3
                )
                ttk.Label(
                    group, text=f"Built in: {profile.oauth.authority}", foreground="#555"
                ).grid(row=6, column=1, sticky="w")

                ttk.Label(group, text="OAuth scopes").grid(row=7, column=0, sticky="nw", pady=3)
                text = tk.Text(group, height=3, wrap="none")
                text.grid(row=7, column=1, sticky="ew", pady=3)
                text.insert("1.0", "\n".join(oauth.get("scopes") or []))
                self.provider_scopes[provider] = text
                ttk.Label(
                    group,
                    text=f"One per line. Built in: {' '.join(profile.oauth.scopes)}",
                    foreground="#555",
                    wraplength=520,
                ).grid(row=8, column=1, sticky="w")

    def _save_providers(self) -> None:
        doc = load_document(self.path)
        for provider, variables in self.provider_vars.items():
            scopes_widget = self.provider_scopes.get(provider)
            scopes_text = scopes_widget.get("1.0", "end") if scopes_widget is not None else ""
            try:
                fields = parse_provider_form(
                    {
                        "host": variables["host"].get(),
                        "port": variables["port"].get(),
                        "ssl": _SSL_CHOICES[variables["ssl"].get()],
                        "authority": variables["authority"].get(),
                    },
                    scopes_text,
                )
            except ValueError as exc:
                self.var_status.set(f"{provider}: {exc}")
                return
            if any(value not in ("", [], None) for value in fields.values()):
                upsert_provider_override(doc, provider, fields)
            else:
                remove_provider_override(doc, provider)

        try:
            save_document(self.path, doc)
        except ValueError as exc:
            self.var_status.set(str(exc))
            return
        self.refresh()
        self.var_status.set("Provider overrides saved.")

    # -- doctor tab ------------------------------------------------------
    def _build_doctor(self) -> None:
        tk, ttk = self._tk, self._ttk
        frame = self.tab_doctor
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        ttk.Label(
            frame,
            text=(
                "Checks your config, your stored credentials, and then actually connects "
                "to each server and lists its folders."
            ),
            wraplength=680,
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        self.btn_doctor = ttk.Button(frame, text="Run doctor", command=self._run_doctor)
        self.btn_doctor.grid(row=1, column=0, sticky="w", pady=PAD)

        wrapper = ttk.Frame(frame)
        wrapper.grid(row=2, column=0, sticky="nsew")
        self.doctor_out = tk.Text(wrapper, wrap="none", font="TkFixedFont", state="disabled")
        scroll = ttk.Scrollbar(wrapper, orient="vertical", command=self.doctor_out.yview)
        self.doctor_out.configure(yscrollcommand=scroll.set)
        self.doctor_out.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _run_doctor(self) -> None:
        self.btn_doctor.configure(state="disabled")
        self.var_status.set("Connecting to your mail servers…")
        self.work.start(lambda: doctor_text(run_doctor(connect=True)))

    def _show_doctor_result(self, text: Any) -> None:
        self.btn_doctor.configure(state="normal")
        self.var_status.set("")
        self.doctor_out.configure(state="normal")
        self.doctor_out.delete("1.0", "end")
        self.doctor_out.insert("1.0", str(text))
        self.doctor_out.configure(state="disabled")


def run(page: str = "accounts") -> int:
    """Open the settings window. Returns a process exit code."""
    try:
        import tkinter as tk
    except Exception as exc:  # noqa: BLE001 - ImportError on a Python without Tk
        print(f"No graphical display available ({exc}).", file=sys.stderr)
        print("Run `rubit-mcp-mail doctor` to check the config from the terminal.")
        return 1

    # Lets the release build prove that Tcl/Tk actually made it into the frozen
    # bundle - a failure that otherwise only shows up on a user's machine.
    selftest = bool(os.environ.get("RUBIT_MCP_MAIL_SELFTEST"))

    try:
        root = tk.Tk()
    except Exception as exc:  # noqa: BLE001 - TclError with no display
        print(f"No graphical display available ({exc}).", file=sys.stderr)
        print("Run `rubit-mcp-mail doctor` to check the config from the terminal.")
        return 1

    if selftest:
        print(f"Tk {tk.TkVersion} available")
        root.destroy()
        return 0

    ConfigWindow(root, page=page)
    root.mainloop()
    return 0
