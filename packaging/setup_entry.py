"""PyInstaller entry point for the installer a user downloads and runs.

Separate from `cli_entry.py` because the two binaries are built differently and
do different jobs: this one is windowed and opens the setup wizard, while the
server it installs is a console build that Claude launches with `serve` and
talks to over stdio.

See cli_entry.py for why entry points live outside the package.
"""

from rubit_mcp_mail.installer_gui import run

if __name__ == "__main__":
    raise SystemExit(run())
