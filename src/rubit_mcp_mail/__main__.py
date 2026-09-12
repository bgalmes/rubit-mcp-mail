"""CLI: serve | install | auth | doctor | gui.

`auth` is a CLI command rather than an MCP tool because the device-code flow is
interactive and blocking - it is a one-time setup step, not something a model
should drive.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .diagnostics import AccountReport, Report, run_doctor
from .session import Session

CONFIG_TEMPLATE = """# ~/.config/rubit-mcp-mail/config.toml
download_dir = "~/Downloads/rubit-mcp-mail"

[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "<Application (client) ID from your Azure app registration>"

# Any other IMAP server, e.g. Fastmail:
# [accounts.personal]
# provider = "generic"
# email    = "you@fastmail.com"
# host     = "imap.fastmail.com"
"""


def cmd_serve(_args: argparse.Namespace) -> int:
    from .server import main as serve_main

    serve_main()
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .webui import serve

    serve(port=args.port, open_browser=not args.no_browser, path=getattr(args, "path", "/"))
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    from .installer_gui import run

    return run(force_console=args.console)


def cmd_auth(args: argparse.Namespace) -> int:
    session = Session()
    try:
        account = session.account(args.account)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    strategy = session.auth_for(account)
    try:
        print(strategy.interactive_setup())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\nNow verify it works:  rubit-mcp-mail doctor {account.name}")
    return 0


def _print_account(report: AccountReport) -> None:
    print(f"\n=== {report.name} ===")
    if report.error and not report.auth_state:
        print(f"  FAIL  {report.error}")
        return

    print(f"  provider  {report.provider}  ({report.host}:{report.port}, ssl={report.ssl})")
    print(f"  email     {report.email}")
    detail = f"  - {report.auth_detail}" if report.auth_detail else ""
    print(f"  auth      {report.auth_state}{detail}")
    if report.auth_state != "ok":
        print(f"  ->  run: rubit-mcp-mail auth {report.name}")
        return
    if report.error:
        print(f"  FAIL  {report.error}")
        return

    print(f"  connected capabilities: {' '.join(report.capabilities[:12])}")
    print(f"  folders   {len(report.folders)} found")
    for folder in report.folders:
        counts = ""
        if folder.messages is not None:
            counts = f"{folder.messages:>6} msgs, {folder.unseen or 0} unread"
        print(f"    [{folder.role:<7}] {folder.name:<28} {counts}")


def cmd_doctor(args: argparse.Namespace) -> int:
    names = [args.account] if args.account else None
    report: Report = run_doctor(names)
    print(f"config: {report.config_path}")

    if report.missing_config:
        print("\nNo config file yet. Create it with:\n")
        print(f"  mkdir -p {report.config_path.parent}")
        print(f"  cat > {report.config_path} <<'EOF'")
        print(CONFIG_TEMPLATE.rstrip())
        print("  EOF")
        print("\nOr set one up without writing TOML by hand:")
        print("  rubit-mcp-mail install   (step-by-step setup wizard)")
        print("  rubit-mcp-mail gui       (edit the config in a browser)")
        return 1
    if report.config_error:
        print(f"\nerror: {report.config_error}", file=sys.stderr)
        return 1

    print(f"downloads: {report.download_dir}")
    for name, keys in report.provider_overrides.items():
        print(f"provider overrides: {name} ({', '.join(keys)})")
    print(f"secrets: {report.secrets_backend}")
    if report.secrets_warning:
        # The same binary run from a GUI-launched process may resolve a
        # different backend, which is the classic "works in the terminal but
        # not under the MCP client" failure.
        print("  note: credentials in the OS keyring are not readable here.")

    if not report.accounts:
        print("\nNo accounts configured.")
        return 1

    for account in report.accounts:
        _print_account(account)

    print()
    if report.failures:
        print(f"{report.failures} account(s) not working.")
        return 1
    print("All accounts OK.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="rubit-mcp-mail", description="Read-only MCP server for reading mail over IMAP."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Run the MCP server on stdio (default).").set_defaults(
        func=cmd_serve
    )

    install = sub.add_parser(
        "install", help="Set up an account step by step: config, sign-in, and Claude."
    )
    install.add_argument(
        "--console", action="store_true", help="Use text prompts instead of a window."
    )
    install.set_defaults(func=cmd_install)

    auth = sub.add_parser("auth", help="Sign in to an account (one-time, interactive).")
    auth.add_argument("account", nargs="?", help="Account name; optional if only one.")
    auth.set_defaults(func=cmd_auth)

    doctor = sub.add_parser("doctor", help="Check config, auth, and connectivity.")
    doctor.add_argument("account", nargs="?", help="Only check this account.")
    doctor.set_defaults(func=cmd_doctor)

    for name, help_text, path in (
        ("gui", "Open a local web GUI to view and edit the config.", "/"),
        ("permissions", "Open the GUI on the allow/forbid-tools page.", "/permissions"),
    ):
        gui = sub.add_parser(name, help=help_text)
        gui.add_argument(
            "--port", type=int, default=0, help="Port to bind (default: pick a free one)."
        )
        gui.add_argument(
            "--no-browser", action="store_true", help="Don't open a browser automatically."
        )
        gui.set_defaults(func=cmd_gui, path=path)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        # stderr only: stdout is the MCP transport and must stay clean.
        stream=sys.stderr,
    )
    if not getattr(args, "func", None):
        args.func = cmd_serve
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
