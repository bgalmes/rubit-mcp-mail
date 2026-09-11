"""Setup wizard core: everything the installer does, minus the window.

`installer_gui` is a tkinter front end over this module and `console_wizard`
below is the fallback for a machine with no usable display; both collect a
`SetupPlan` and hand it to `apply_setup`, so the two front ends cannot drift
apart in what they actually do.

Nothing here imports tkinter, which is what keeps it testable on a headless
box.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path

from . import claude_registration
from .auth import build_auth
from .auth.base import AuthUI
from .config import Account, add_account, config_path, load_config
from .providers import THUNDERBIRD_CLIENT_ID
from .secrets import SecretStore

log = logging.getLogger(__name__)

#: Name the MCP server executable is installed under.
SERVER_BINARY_NAME = "rubit-mcp-mail.exe" if sys.platform == "win32" else "rubit-mcp-mail"

#: Offered as suggestions on the "other provider" page (same list as the README).
KNOWN_IMAP_HOSTS: dict[str, str] = {
    "Gmail": "imap.gmail.com",
    "Fastmail": "imap.fastmail.com",
    "iCloud": "imap.mail.me.com",
    "Yahoo": "imap.mail.yahoo.com",
}


@dataclass
class SetupPlan:
    """What the user chose. Everything needed to write one account."""

    name: str
    provider: str
    email: str
    host: str | None = None
    client_id: str | None = None
    # Carried through unchanged when repairing an account, so re-running the
    # wizard doesn't quietly drop a hand-tuned port or ssl setting.
    port: int | None = None
    ssl: bool | None = None


@dataclass
class SetupResult:
    """What actually happened, for the final page to report."""

    config_file: Path
    secret_backend: str
    server_path: Path | None = None
    signin_message: str | None = None
    signin_error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.signin_error is None and self.server_path is not None


# -- where things live ---------------------------------------------------
def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than a source tree."""
    return bool(getattr(sys, "frozen", False))


def default_install_dir() -> Path:
    """Where the MCP server executable is installed to stay.

    It has to outlive the installer itself: the user may run setup from their
    Downloads folder and then delete it, while Claude keeps launching the path
    we registered for as long as the server is configured.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Programs" / "rubit-mcp-mail"
    return Path.home() / ".local" / "share" / "rubit-mcp-mail" / "bin"


def bundled_server_binary() -> Path | None:
    """The server executable packed inside the installer, when there is one."""
    if not is_frozen():
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    candidate = Path(meipass) / SERVER_BINARY_NAME
    return candidate if candidate.exists() else None


def install_server_binary(source: Path, target_dir: Path) -> Path:
    """Copy the server executable into `target_dir` and make it runnable."""
    target = target_dir / SERVER_BINARY_NAME
    if target.exists() and source.resolve() == target.resolve():
        return target

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(source, target)
    except PermissionError as exc:
        # Windows locks a running executable, so this is the "Claude is still
        # running the old copy" case rather than anything the user did wrong.
        raise PermissionError(
            f"Could not replace {target} ({exc}). Quit Claude Desktop, which may "
            "still be running the mail server, and run setup again."
        ) from None
    if os.name == "posix":
        target.chmod(0o755)
    return target


def dev_server_command() -> Path:
    """The `rubit-mcp-mail` to register when setup runs from a source install.

    Only reached via `rubit-mcp-mail install` in a checkout: there is nothing
    to unpack, so we register the console script already on this machine.
    """
    if found := shutil.which("rubit-mcp-mail"):
        return Path(found)
    sibling = Path(sys.executable).parent / SERVER_BINARY_NAME
    if sibling.exists():
        return sibling
    raise FileNotFoundError(
        "Could not find the rubit-mcp-mail executable to register. Install the "
        "package (pip install -e .) so its console script exists, or run the "
        "packaged installer instead."
    )


def ensure_server_installed(install_dir: Path | None = None) -> Path:
    """Put the server executable somewhere permanent and return its path."""
    if bundled := bundled_server_binary():
        return install_server_binary(bundled, install_dir or default_install_dir())
    return dev_server_command()


# -- reading what is already there ---------------------------------------
def existing_accounts(path: Path | None = None) -> dict[str, Account]:
    """Accounts already configured, or {} when there is nothing usable yet."""
    try:
        return load_config(path or config_path()).accounts
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        # A config too broken to load is exactly what re-running setup is meant
        # to repair, so carry on with an empty list rather than dead-ending.
        log.debug("ignoring unreadable config: %s", exc)
        return {}


def plan_from_existing(account: Account) -> SetupPlan:
    """Pre-fill the form from an account being repaired."""
    return SetupPlan(
        name=account.name,
        provider=account.provider,
        email=account.email,
        host=account.host,
        client_id=account.client_id,
        port=account.port,
        ssl=account.ssl,
    )


def suggest_account_name(email: str, taken: Collection[str] = ()) -> str:
    """A short, unique config key derived from an email address."""
    local = email.split("@", 1)[0].lower()
    base = re.sub(r"[^a-z0-9_-]", "", local) or "mail"
    name = base
    n = 2
    while name in taken:
        name = f"{base}{n}"
        n += 1
    return name


def default_client_id(existing: str | None = None) -> str:
    """What to pre-fill the Outlook client_id field with."""
    return existing or THUNDERBIRD_CLIENT_ID


def validate_plan(plan: SetupPlan) -> str | None:
    """Human-readable reason this form isn't ready yet, or None if it is.

    Shared by both front ends so the wizard can refuse to advance with the
    same wording, before anything is written.
    """
    if not plan.email.strip():
        return "Enter the email address of the mailbox you want to read."
    if "@" not in plan.email:
        return f"{plan.email!r} does not look like an email address."
    if not plan.name.strip():
        return "Enter a short name for this account."
    if plan.provider == "generic" and not (plan.host or "").strip():
        return "Enter the IMAP server for this mailbox, e.g. imap.fastmail.com."
    if plan.provider == "outlook" and not (plan.client_id or "").strip():
        return "Enter the Outlook client ID, or use the suggested default."
    return None


# -- doing the work ------------------------------------------------------
def run_signin(account: Account, store: SecretStore, ui: AuthUI | None = None) -> str:
    """Run the account's real interactive sign-in flow."""
    return build_auth(account, store).interactive_setup(ui)


def register_clients(server_path: Path, store: SecretStore) -> list[str]:
    """Register the server with whichever Claude clients are on this machine.

    Neither client is required, and failing to reach one must not lose the work
    already done, so every branch returns a line for the summary rather than
    raising.
    """
    notes: list[str] = []
    found_any = False

    if claude_registration.claude_code_available():
        found_any = True
        try:
            ok, output = claude_registration.register_claude_code(server_path)
            if ok:
                notes.append("Claude Code: registered as 'rubit-mail'.")
            else:
                notes.append(f"Claude Code: registration failed ({output or 'no output'}).")
        except Exception as exc:  # noqa: BLE001 - report, never abort setup
            notes.append(f"Claude Code: registration failed ({exc}).")
    else:
        notes.append("Claude Code: not installed here, skipped.")

    if claude_registration.claude_desktop_detected():
        found_any = True
        try:
            path = claude_registration.register_claude_desktop(
                server_path, needs_no_keyring=store.unavailable_reason is not None
            )
            notes.append(f"Claude Desktop: registered in {path}.")
            notes.append("Restart Claude Desktop for it to pick up the server.")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Claude Desktop: registration failed ({exc}).")
    else:
        notes.append("Claude Desktop: not installed here, skipped.")

    if not found_any:
        notes.append(
            "Neither Claude Desktop nor Claude Code was found. Install one and "
            "run this setup again to connect your mail to it."
        )
    return notes


def _account_for(path: Path, plan: SetupPlan) -> Account:
    """The account we just wrote, read back so [providers.*] overrides apply."""
    try:
        return load_config(path).account(plan.name)
    except Exception as exc:  # noqa: BLE001
        # Another account in the file being unloadable must not block signing
        # in to this one. Endpoint overrides are lost in that corner, which is
        # why it is a fallback and not the normal path.
        log.debug("falling back to an un-overridden account: %s", exc)
        return Account(
            name=plan.name,
            provider=plan.provider,
            email=plan.email,
            client_id=plan.client_id,
            host=plan.host,
            port=plan.port,
            ssl=plan.ssl,
        )


def apply_setup(
    plan: SetupPlan,
    *,
    config_file: Path | None = None,
    install_dir: Path | None = None,
    ui: AuthUI | None = None,
    store: SecretStore | None = None,
) -> SetupResult:
    """Write the config, install the server, sign in, and register with Claude.

    Only the config write is fatal: past that point each step records what
    happened and setup carries on, so a machine that fails at sign-in still
    ends up configured and registered, and re-running fixes just the part that
    failed.
    """
    path = config_file or config_path()
    store = store or SecretStore()

    add_account(
        path,
        plan.name,
        plan.provider,
        plan.email,
        client_id=plan.client_id,
        host=plan.host,
        port=plan.port,
        ssl=plan.ssl,
    )
    result = SetupResult(config_file=path, secret_backend=store.backend_name)

    try:
        result.server_path = ensure_server_installed(install_dir)
    except Exception as exc:  # noqa: BLE001
        result.notes.append(f"Could not install the mail server executable: {exc}")

    try:
        result.signin_message = run_signin(_account_for(path, plan), store, ui)
    except Exception as exc:  # noqa: BLE001
        result.signin_error = str(exc)
    # Read after signing in: the credential we just stored is what decides
    # whether the file store exists, and the summary should say where it went.
    result.secret_backend = store.backend_name

    if result.server_path is not None:
        result.notes.extend(register_clients(result.server_path, store))
    return result


# -- console fallback ----------------------------------------------------
def _ask(
    input_fn: Callable[[str], str],
    out: Callable[[str], None],
    prompt: str,
    default: str | None = None,
) -> str:
    label = f"{prompt} [{default}]: " if default else f"{prompt}: "
    while True:
        if answer := (input_fn(label).strip() or (default or "")):
            return answer
        out("Please enter a value.")


def _collect_plan_console(
    input_fn: Callable[[str], str],
    out: Callable[[str], None],
    accounts: dict[str, Account],
) -> SetupPlan | None:
    if accounts:
        out("")
        out("Already set up: " + ", ".join(sorted(accounts)))
        choice = _ask(input_fn, out, "Add a new account or repair one? (new/repair)", "new")
        if choice.lower().startswith("r"):
            name = _ask(input_fn, out, "Which account", sorted(accounts)[0])
            if name not in accounts:
                out(f"No account named {name!r}.")
                return None
            plan = plan_from_existing(accounts[name])
            out(f"Repairing {plan.name} <{plan.email}>.")
            return plan

    out("")
    answer = _ask(input_fn, out, "Mail provider? (outlook/other)", "outlook")
    # Matched exactly rather than by prefix: "other" also starts with an "o",
    # and reading that as Outlook would set up entirely the wrong account.
    outlook_words = {"outlook", "o", "hotmail", "microsoft"}
    provider = "outlook" if answer.lower() in outlook_words else "generic"

    email = _ask(input_fn, out, "Email address")
    name = _ask(input_fn, out, "Short name for this account", suggest_account_name(email, accounts))

    host = client_id = None
    if provider == "generic":
        out("")
        out("Known servers: " + ", ".join(f"{k} = {v}" for k, v in KNOWN_IMAP_HOSTS.items()))
        host = _ask(input_fn, out, "IMAP server")
    else:
        out("")
        out("Outlook needs an Azure 'client ID'. The suggested one below is the")
        out("public ID Thunderbird uses, which works without registering your own")
        out("app - Microsoft's consent screen will say 'Thunderbird'.")
        client_id = _ask(input_fn, out, "Client ID", default_client_id())

    return SetupPlan(name=name, provider=provider, email=email, host=host, client_id=client_id)


def _report_console(result: SetupResult, out: Callable[[str], None]) -> None:
    out("")
    out("-" * 62)
    if result.signin_message:
        out(result.signin_message)
    if result.signin_error:
        out(f"Sign-in did not finish: {result.signin_error}")
    out("")
    out(f"Config:  {result.config_file}")
    out(f"Secrets: {result.secret_backend}")
    if result.server_path:
        out(f"Server:  {result.server_path}")
    for note in result.notes:
        out(note)
    if result.server_path:
        out("")
        out(f'Check it works:  "{result.server_path}" doctor')


def console_wizard(
    *,
    input_fn: Callable[[str], str] = input,
    ui: AuthUI | None = None,
    config_file: Path | None = None,
    install_dir: Path | None = None,
    store: SecretStore | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Text version of the wizard, for a machine with no usable display."""
    path = config_file or config_path()

    out("")
    out("rubit-mcp-mail setup")
    out("====================")
    out(f"Config file: {path}")

    accounts = existing_accounts(path)
    plan = _collect_plan_console(input_fn, out, accounts)
    if plan is None:
        return 1
    if problem := validate_plan(plan):
        out(problem)
        return 1

    result = apply_setup(plan, config_file=path, install_dir=install_dir, ui=ui, store=store)
    _report_console(result, out)
    return 0 if result.ok else 1
