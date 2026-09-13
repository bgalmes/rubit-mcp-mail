"""Windows' "Add/Remove Programs" entry.

This installer never asks for admin rights - everything it writes lives under
the current user's own profile - so the entry goes under `HKEY_CURRENT_USER`
rather than `HKEY_LOCAL_MACHINE`. Windows' "Apps & Features" page has listed
per-user entries there since Windows 7, without elevation.

Split the same way as shortcuts.py: a pure function builds the values that
would be written, checkable on any platform, and a thin wrapper does the
actual `winreg` calls and never raises - a machine that refuses this write
still has a working, uninstallable-by-hand install, and must not lose that
over a cosmetic Control Panel entry.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Subkey of HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall.
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\rubit-mcp-mail"

DISPLAY_NAME = "rubit-mcp-mail"
PUBLISHER = "rubit-mcp-mail contributors"


def registry_values(gui_exe: Path, install_dir: Path) -> dict[str, str | int]:
    """The values Add/Remove Programs reads for this entry.

    Kept separate from the `winreg` calls themselves so the shape of what
    gets written is testable on any platform.
    """
    return {
        "DisplayName": DISPLAY_NAME,
        "UninstallString": f'"{gui_exe}" uninstall',
        "DisplayIcon": str(gui_exe),
        "Publisher": PUBLISHER,
        "InstallLocation": str(install_dir),
        # No modify/repair flow exists - this is a single settings binary.
        "NoModify": 1,
        "NoRepair": 1,
    }


def register(gui_exe: Path, install_dir: Path) -> None:
    """Add the Add/Remove Programs entry. A no-op off Windows."""
    if sys.platform != "win32":
        return
    import winreg

    values = registry_values(gui_exe, install_dir)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        for name, value in values.items():
            kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
            winreg.SetValueEx(key, name, 0, kind, value)


def unregister() -> None:
    """Remove the Add/Remove Programs entry. A no-op off Windows, or if absent."""
    if sys.platform != "win32":
        return
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass
