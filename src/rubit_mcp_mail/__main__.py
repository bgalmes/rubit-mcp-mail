"""CLI: serve | auth | doctor.

`auth` is a CLI command rather than an MCP tool because the device-code flow is
interactive and blocking - it is a one-time setup step, not something a model
should drive.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import config_path, load_config
from .secrets import SecretStore
from .session import Session

CONFIG_TEMPLATE = '''# ~/.config/rubit-mcp-mail/config.toml
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
'''


def cmd_serve(_args: argparse.Namespace) -> int:
    from .server import main as serve_main

    serve_main()
    return 0


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


def cmd_doctor(args: argparse.Namespace) -> int:
    path = config_path()
    print(f"config: {path}")
    try:
        config = load_config()
    except FileNotFoundError:
        print("\nNo config file yet. Create it with:\n")
        print(f"  mkdir -p {path.parent}")
        print(f"  cat > {path} <<'EOF'")
        print(CONFIG_TEMPLATE.rstrip())
        print("  EOF")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1

    print(f"downloads: {config.download_dir}")
    if config.providers:
        for name, overrides in sorted(config.providers.items()):
            keys = []
            for key, value in overrides.items():
                if key == "oauth" and isinstance(value, dict):
                    keys.extend(f"oauth.{sub}" for sub in value)
                else:
                    keys.append(key)
            print(f"provider overrides: {name} ({', '.join(sorted(keys))})")
    session = Session(config=config, store=SecretStore())

    names = [args.account] if args.account else list(config.accounts)
    if not names:
        print("\nNo accounts configured.")
        return 1

    failures = 0
    for name in names:
        print(f"\n=== {name} ===")
        try:
            account = session.account(name)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {exc}")
            failures += 1
            continue

        profile = account.profile
        print(f"  provider  {account.provider}  ({profile.host}:{profile.port}, ssl={profile.ssl})")
        print(f"  email     {account.email}")

        state, detail = session.auth_for(account).status()
        print(f"  auth      {state}" + (f"  - {detail}" if detail else ""))
        if state != "ok":
            print(f"  ->  run: rubit-mcp-mail auth {name}")
            failures += 1
            continue

        backend = session.backend(name)
        try:
            caps = backend.capabilities()
            print(f"  connected capabilities: {' '.join(caps[:12])}")
            folders = backend.list_folders()
            print(f"  folders   {len(folders)} found")
            for folder in folders:
                counts = ""
                if folder.messages is not None:
                    counts = f"{folder.messages:>6} msgs, {folder.unseen or 0} unread"
                print(f"    [{folder.role:<7}] {folder.name:<28} {counts}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {type(exc).__name__}: {exc}")
            failures += 1
        finally:
            backend.close()

    print()
    if failures:
        print(f"{failures} account(s) not working.")
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

    auth = sub.add_parser("auth", help="Sign in to an account (one-time, interactive).")
    auth.add_argument("account", nargs="?", help="Account name; optional if only one.")
    auth.set_defaults(func=cmd_auth)

    doctor = sub.add_parser("doctor", help="Check config, auth, and connectivity.")
    doctor.add_argument("account", nargs="?", help="Only check this account.")
    doctor.set_defaults(func=cmd_doctor)

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
