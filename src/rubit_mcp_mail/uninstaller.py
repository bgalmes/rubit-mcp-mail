"""Uninstall wizard core: everything the uninstaller does, minus the window.

Mirrors installer.py's split: `uninstaller_gui` is a tkinter front end over
this module and `console_uninstall` below is the fallback for a machine with
no usable display. Nothing here imports tkinter, which is what keeps it
testable on a headless box.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from . import claude_registration, shortcuts, uninstall_registry
from .auth import build_auth
from .config import config_path
from .installer import default_install_dir, existing_accounts, is_frozen
from .secrets import SecretStore

#: Where the mail attachments the server downloads end up by default. Created
#: at runtime by the server, not by the installer, so uninstall leaves it be -
#: deleting a user's saved files as a side effect of removing the app would be
#: a nasty surprise.
_DOWNLOAD_DIR_NOTE = "Downloaded mail attachments (in your Downloads folder) were left in place."


@dataclass
class UninstallResult:
    """What actually happened, for the final page to report."""

    config_file: Path
    install_dir: Path
    notes: list[str] = field(default_factory=list)


def _remove_config_and_secrets(config_file: Path, store: SecretStore) -> list[str]:
    """Delete the config file and the secrets fallback file, by name only.

    Deliberately not `shutil.rmtree(config_file.parent)`: the secrets
    fallback path does not honour `RUBIT_MCP_MAIL_CONFIG` the way
    `config_path()` does, so the two files are not guaranteed to be siblings,
    and recursively deleting "the config directory" could take something else
    with it. Removing the two known files, then tidying up an empty parent,
    is safe regardless of where either of them actually lives.
    """
    notes: list[str] = []
    for label, target in (("config", config_file), ("stored secrets", store.path)):
        try:
            existed = target.exists()
            target.unlink(missing_ok=True)
        except OSError as exc:
            notes.append(f"Could not remove the {label} file ({exc}).")
            continue
        if existed:
            notes.append(f"Removed {target}.")
    for directory in {config_file.parent, store.path.parent}:
        try:
            directory.rmdir()
        except OSError:
            pass  # not empty, or already gone - either is fine
    return notes


def windows_cleanup_script(install_dir: PurePath) -> str:
    """PowerShell that deletes `install_dir` once nothing still has it open.

    The process running this code (the uninstaller itself) lives inside
    `install_dir` on a frozen Windows build, and Windows refuses to delete a
    running executable's file. So this is written to run detached, after the
    uninstaller has already exited: it retries rather than sleeping a fixed
    amount, because how long Windows takes to fully unmap the exe depends on
    things (AV scanning, disk speed) this code has no way to predict. It
    deletes itself last so it doesn't litter the temp directory.
    """
    target = "'" + str(install_dir).replace("'", "''") + "'"
    return f"""$ErrorActionPreference = 'SilentlyContinue'
$target = {target}
for ($i = 0; $i -lt 20; $i++) {{
    if (-not (Test-Path -LiteralPath $target)) {{ break }}
    Remove-Item -LiteralPath $target -Recurse -Force
    if (-not (Test-Path -LiteralPath $target)) {{ break }}
    Start-Sleep -Milliseconds 500
}}
Remove-Item -LiteralPath $PSCommandPath -Force
"""


def _spawn_windows_cleanup(install_dir: Path) -> None:
    script = windows_cleanup_script(install_dir)
    handle, name = tempfile.mkstemp(
        suffix=".ps1", prefix="rubit-mcp-mail-cleanup-", dir=tempfile.gettempdir()
    )
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(script)
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell, no user input
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            name,
        ],
        # These flags only exist on Windows - this whole function only ever
        # runs there - so they are looked up rather than named directly,
        # which is what keeps this module importable (and type-checkable) on
        # every other platform.
        creationflags=(
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
        close_fds=True,
    )


def _remove_install_dir(install_dir: Path) -> str | None:
    """Remove the installed binaries. Returns a note, or None if nothing was there."""
    if not install_dir.exists():
        return None
    if is_frozen() and sys.platform == "win32":
        try:
            _spawn_windows_cleanup(install_dir)
        except OSError as exc:
            return f"Could not schedule removal of {install_dir} ({exc})."
        return f"{install_dir} will be removed once this window closes."
    shutil.rmtree(install_dir, ignore_errors=True)
    return f"Removed {install_dir}."


def apply_uninstall(
    *,
    config_file: Path | None = None,
    install_dir: Path | None = None,
    store: SecretStore | None = None,
) -> UninstallResult:
    """Undo everything `apply_setup` did.

    Every step is best-effort: one failing must not stop the rest, the same
    philosophy `apply_setup` follows, since a partially-broken install is
    exactly the situation where uninstalling needs to work.
    """
    path = config_file or config_path()
    store = store or SecretStore()
    install_dir = install_dir or default_install_dir()
    result = UninstallResult(config_file=path, install_dir=install_dir)

    for account in existing_accounts(path).values():
        try:
            store.delete(build_auth(account, store).secret_key)
        except Exception as exc:  # noqa: BLE001
            result.notes.append(f"Could not remove stored credentials for {account.name!r}: {exc}.")

    if claude_registration.claude_code_available():
        try:
            ok, output = claude_registration.unregister_claude_code()
            result.notes.append(
                "Claude Code: unregistered."
                if ok
                else f"Claude Code: {output or 'nothing to remove'}."
            )
        except Exception as exc:  # noqa: BLE001
            result.notes.append(f"Claude Code: could not unregister ({exc}).")

    try:
        if removed_from := claude_registration.unregister_claude_desktop():
            result.notes.append(f"Claude Desktop: unregistered from {removed_from}.")
    except Exception as exc:  # noqa: BLE001
        result.notes.append(f"Claude Desktop: could not update config ({exc}).")

    result.notes.extend(shortcuts.remove_shortcuts())

    try:
        uninstall_registry.unregister()
    except Exception as exc:  # noqa: BLE001
        result.notes.append(f"Could not remove the Windows uninstall entry ({exc}).")

    result.notes.extend(_remove_config_and_secrets(path, store))

    if note := _remove_install_dir(install_dir):
        result.notes.append(note)

    result.notes.append(_DOWNLOAD_DIR_NOTE)
    return result


# -- console fallback ----------------------------------------------------
def console_uninstall(
    *,
    input_fn: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    config_file: Path | None = None,
    install_dir: Path | None = None,
    store: SecretStore | None = None,
) -> int:
    """Text version of the uninstaller, for a machine with no usable display."""
    out("")
    out("rubit-mcp-mail uninstall")
    out("=========================")
    out("This removes the installed server and settings binaries, your")
    out("configured accounts, stored credentials, shortcuts, and the")
    out("registration with Claude Desktop/Claude Code.")
    answer = input_fn("Continue? [y/N]: ").strip().lower()
    if not answer.startswith("y"):
        out("Cancelled.")
        return 1

    result = apply_uninstall(config_file=config_file, install_dir=install_dir, store=store)
    out("")
    for note in result.notes:
        out(note)
    return 0
