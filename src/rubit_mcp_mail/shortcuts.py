"""Making the settings GUI clickable: Start Menu, Desktop, application menu.

This is the half of "no terminal required" that the window itself cannot
provide. The setup wizard installs the GUI executable somewhere permanent and
then calls in here to give the user something to click.

Follows the same convention as `installer.register_clients`: every branch
returns a line for the setup summary and nothing raises. A desktop environment
that does not want our shortcut, or a locked-down Windows policy, must not
undo a mailbox that is otherwise configured and working.

The two platform halves are split into a pure "what to write" function and a
thin "write it" wrapper, so the awkward half - PowerShell quoting, .desktop
syntax - is checkable on any machine.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePath

#: Basename used for the .desktop file, the .lnk files and the icon.
SHORTCUT_NAME = "rubit-mcp-mail"
DISPLAY_NAME = "rubit-mcp-mail Settings"
COMMENT = "Set up and manage the mailboxes Claude can read"
ICON_FILE = "rubit-mcp-mail.png"

#: Second Linux menu entry: there is no package manager to hook an "uninstall"
#: action into, so this is that platform's equivalent of Windows' Add/Remove
#: Programs entry (see uninstall_registry.py) - something to click in the
#: application menu that removes everything setup created.
UNINSTALL_SHORTCUT_NAME = f"{SHORTCUT_NAME}-uninstall"
UNINSTALL_DISPLAY_NAME = "Uninstall rubit-mcp-mail"


def icon_source() -> Path | None:
    """The icon shipped with this build, wherever it ended up.

    Frozen, PyInstaller unpacks `--add-data` next to the bundle root; from a
    source checkout it is still in `packaging/icons`. Returns None rather than
    failing: a shortcut without an icon is worth having.
    """
    candidates = []
    if meipass := getattr(sys, "_MEIPASS", None):
        candidates.append(Path(meipass) / ICON_FILE)
    candidates.append(Path(__file__).resolve().parents[2] / "packaging" / "icons" / ICON_FILE)
    return next((path for path in candidates if path.is_file()), None)


# -- Linux -------------------------------------------------------------------
def desktop_entry(executable: PurePath, arguments: str = "", *, icon: str = SHORTCUT_NAME) -> str:
    """The .desktop file contents for `executable`.

    `Exec` is quoted because the install directory sits under the user's home,
    which may well contain a space.

    Takes a PurePath, not a Path: nothing here touches the filesystem, so the
    Linux output stays checkable from a Windows machine and vice versa.
    """
    exec_line = f'"{executable}" {arguments}'.strip()
    return f"""[Desktop Entry]
Type=Application
Name={DISPLAY_NAME}
Comment={COMMENT}
Exec={exec_line}
Icon={icon}
Terminal=false
Categories=Network;Email;Settings;
Keywords=mail;imap;claude;mcp;
"""


def uninstall_desktop_entry(executable: PurePath, *, icon: str = SHORTCUT_NAME) -> str:
    """The .desktop file contents for the "Uninstall" menu entry.

    Always passes `uninstall` regardless of what the settings shortcut was
    given: this always points at removing the install, never anything else.
    """
    exec_line = f'"{executable}" uninstall'
    return f"""[Desktop Entry]
Type=Application
Name={UNINSTALL_DISPLAY_NAME}
Comment=Remove rubit-mcp-mail and everything its setup created
Exec={exec_line}
Icon={icon}
Terminal=false
Categories=System;
Keywords=uninstall;remove;rubit-mcp-mail;
"""


def _applications_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "applications"


def _icon_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "icons" / "hicolor" / "256x256" / "apps"


def _create_linux(executable: Path, arguments: str) -> list[str]:
    notes: list[str] = []

    icon_name = SHORTCUT_NAME
    if source := icon_source():
        try:
            target_dir = _icon_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target_dir / ICON_FILE)
        except OSError as exc:
            # A themed icon is cosmetic; fall back to a stock one by name.
            notes.append(f"Could not install the icon ({exc}).")
            icon_name = "mail-message-new"

    directory = _applications_dir()
    path = directory / f"{SHORTCUT_NAME}.desktop"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(desktop_entry(executable, arguments, icon=icon_name), encoding="utf-8")
        # Some desktops still refuse to launch a non-executable entry.
        path.chmod(0o755)
    except OSError as exc:
        notes.append(f"Could not create the application menu entry ({exc}).")
        return notes
    notes.append(f"Application menu: added '{DISPLAY_NAME}' ({path}).")

    uninstall_path = directory / f"{UNINSTALL_SHORTCUT_NAME}.desktop"
    try:
        uninstall_path.write_text(
            uninstall_desktop_entry(executable, icon=icon_name), encoding="utf-8"
        )
        uninstall_path.chmod(0o755)
        notes.append(f"Application menu: added '{UNINSTALL_DISPLAY_NAME}' ({uninstall_path}).")
    except OSError as exc:
        notes.append(f"Could not create the uninstall menu entry ({exc}).")

    if updater := shutil.which("update-desktop-database"):
        # Purely to refresh the menu now rather than at next login.
        subprocess.run([updater, str(directory)], capture_output=True, check=False)
    return notes


def _remove_linux() -> list[str]:
    notes: list[str] = []
    directory = _applications_dir()

    for name, label in (
        (SHORTCUT_NAME, DISPLAY_NAME),
        (UNINSTALL_SHORTCUT_NAME, UNINSTALL_DISPLAY_NAME),
    ):
        path = directory / f"{name}.desktop"
        try:
            existed = path.exists()
            path.unlink(missing_ok=True)
        except OSError as exc:
            notes.append(f"Could not remove '{label}' ({exc}).")
            continue
        if existed:
            notes.append(f"Application menu: removed '{label}'.")

    try:
        (_icon_dir() / ICON_FILE).unlink(missing_ok=True)
    except OSError as exc:
        notes.append(f"Could not remove the application icon ({exc}).")

    if updater := shutil.which("update-desktop-database"):
        subprocess.run([updater, str(directory)], capture_output=True, check=False)
    return notes


# -- Windows -----------------------------------------------------------------
def _ps_quote(value: str) -> str:
    """Quote a PowerShell single-quoted string literal."""
    return "'" + value.replace("'", "''") + "'"


def windows_shortcut_script(executable: PurePath, arguments: str = "") -> str:
    """PowerShell that drops a .lnk in the Start Menu and on the Desktop.

    The two folders are resolved by PowerShell rather than here because a
    Windows desktop is routinely redirected - OneDrive being the usual reason -
    and `%USERPROFILE%\\Desktop` is then simply the wrong place.
    """
    target = _ps_quote(str(executable))
    return f"""$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$target = {target}
foreach ($folder in @('Programs', 'Desktop')) {{
    $dir = [Environment]::GetFolderPath($folder)
    if ([string]::IsNullOrEmpty($dir)) {{ continue }}
    $link = $shell.CreateShortcut((Join-Path $dir {_ps_quote(SHORTCUT_NAME + ".lnk")}))
    $link.TargetPath = $target
    $link.Arguments = {_ps_quote(arguments)}
    $link.WorkingDirectory = Split-Path $target
    $link.IconLocation = "$target,0"
    $link.Description = {_ps_quote(COMMENT)}
    $link.Save()
    Write-Output $dir
}}
"""


def _create_windows(executable: Path, arguments: str) -> list[str]:
    script = windows_shortcut_script(executable, arguments)
    handle, name = tempfile.mkstemp(suffix=".ps1", prefix="rubit-mcp-mail-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(script)
        # -File rather than -Command: the script is full of quotes, and passing
        # it as one command line is how that goes wrong.
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return [f"Could not create shortcuts ({exc})."]
    finally:
        Path(name).unlink(missing_ok=True)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no output").strip().splitlines()
        return [f"Could not create shortcuts ({detail[-1] if detail else 'no output'})."]
    return [f"Shortcuts: added '{DISPLAY_NAME}' to the Start Menu and Desktop."]


def windows_shortcut_removal_script() -> str:
    """PowerShell that deletes the .lnk from the Start Menu and the Desktop.

    Resolves the same two special folders `windows_shortcut_script` writes
    into, rather than a hardcoded path, for the same reason: they can be
    redirected (OneDrive being the usual cause).
    """
    return f"""$ErrorActionPreference = 'Stop'
foreach ($folder in @('Programs', 'Desktop')) {{
    $dir = [Environment]::GetFolderPath($folder)
    if ([string]::IsNullOrEmpty($dir)) {{ continue }}
    $link = Join-Path $dir {_ps_quote(SHORTCUT_NAME + ".lnk")}
    if (Test-Path -LiteralPath $link) {{
        Remove-Item -LiteralPath $link -Force
        Write-Output $dir
    }}
}}
"""


def _remove_windows() -> list[str]:
    script = windows_shortcut_removal_script()
    handle, name = tempfile.mkstemp(suffix=".ps1", prefix="rubit-mcp-mail-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(script)
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                name,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return [f"Could not remove shortcuts ({exc})."]
    finally:
        Path(name).unlink(missing_ok=True)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "no output").strip().splitlines()
        return [f"Could not remove shortcuts ({detail[-1] if detail else 'no output'})."]
    return ["Shortcuts: removed from the Start Menu and Desktop."]


# -- entry point -------------------------------------------------------------
def create_shortcuts(executable: Path, arguments: str = "") -> list[str]:
    """Give the user something to click. Returns notes for the setup summary.

    `arguments` is empty for the installed GUI executable, which opens the
    settings window when run with no arguments. It carries `gui` when setup was
    run from a source checkout, where the only thing to point at is the
    console script.
    """
    try:
        if sys.platform == "win32":
            return _create_windows(executable, arguments)
        if sys.platform == "darwin":
            # No macOS build is published yet; when there is one this wants a
            # .app bundle rather than anything resembling the two above.
            return []
        return _create_linux(executable, arguments)
    except Exception as exc:  # noqa: BLE001 - never let a shortcut fail setup
        return [f"Could not create shortcuts ({exc})."]


def remove_shortcuts() -> list[str]:
    """Undo `create_shortcuts`. Returns notes for the uninstall summary.

    Same "never raise" contract as `create_shortcuts`: a desktop environment
    that refuses to cooperate must not abort the rest of the uninstall.
    """
    try:
        if sys.platform == "win32":
            return _remove_windows()
        if sys.platform == "darwin":
            return []
        return _remove_linux()
    except Exception as exc:  # noqa: BLE001
        return [f"Could not remove shortcuts ({exc})."]
