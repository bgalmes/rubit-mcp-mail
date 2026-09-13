"""PyInstaller entry point for the windowed executable.

One binary does two jobs, because they need exactly the same things - Tk, the
config editor, every sign-in flow - and building a second copy of the Python
runtime to hold them again would double the download for nothing:

    (no arguments)      the setup wizard
    gui | permissions   the settings window

Which one a user gets therefore depends only on how it was launched. The file
they download runs the wizard when double-clicked, as it always has; the
shortcut setup creates passes `gui`, so clicking that opens their settings.
The installer copies itself to become that second one - see
`installer.install_gui_binary`.

Separate from `cli_entry.py` because this half is windowed and that half is a
console build Claude talks to over stdio. See cli_entry.py for why entry
points live outside the package.
"""

import sys


def main() -> int:
    argument = sys.argv[1] if len(sys.argv) > 1 else ""

    if argument in ("gui", "permissions"):
        from rubit_mcp_mail.config_gui import run as run_gui

        return run_gui(page="permissions" if argument == "permissions" else "accounts")

    from rubit_mcp_mail.installer_gui import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
