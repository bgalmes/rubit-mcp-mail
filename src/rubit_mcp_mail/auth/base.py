from __future__ import annotations

import getpass
from typing import Protocol, runtime_checkable

from imapclient import IMAPClient

from ..config import Account
from ..secrets import SecretStore


class NeedsAuthError(Exception):
    """Credentials are missing or expired; the user must run the auth command."""

    def __init__(self, account: str, detail: str = "") -> None:
        self.account = account
        suffix = f" ({detail})" if detail else ""
        super().__init__(
            f"Account {account!r} is not authenticated{suffix}. Run: rubit-mcp-mail auth {account}"
        )


@runtime_checkable
class AuthUI(Protocol):
    """How an interactive sign-in talks to whoever is driving it.

    The CLI drives it with a terminal; the setup wizard drives it with a
    window. Keeping this seam narrow is what lets the wizard reuse the real
    sign-in flows below instead of reimplementing them.
    """

    def device_code(self, flow: dict) -> None:
        """Show the user the code and URL of an OAuth device-code flow.

        Called once, before the (blocking) wait for them to approve it.
        """

    def ask_password(self, account: Account) -> str:
        """Collect the app password for `account`. Empty means "cancelled"."""
        ...


class ConsoleAuthUI:
    """Terminal implementation: what `rubit-mcp-mail auth` has always printed."""

    def device_code(self, flow: dict) -> None:
        print()
        print(flow["message"])
        print()
        print("Waiting for you to complete sign-in in the browser...")

    def ask_password(self, account: Account) -> str:
        print(f"Account : {account.name} <{account.email}>")
        print(f"Server  : {account.profile.host}:{account.profile.port}")
        print("Enter the app password for this mailbox (input is hidden).")
        return getpass.getpass("App password: ").strip()


@runtime_checkable
class AuthStrategy(Protocol):
    """Knows how to authenticate an already-connected IMAPClient."""

    #: SecretStore key this strategy persists its credential under. Public so
    #: diagnostics can check whether a credential is present without a network
    #: round-trip.
    secret_key: str

    def __init__(self, account: Account, store: SecretStore) -> None: ...

    def login(self, client: IMAPClient) -> None:
        """Authenticate `client`, or raise NeedsAuthError."""

    def interactive_setup(self, ui: AuthUI | None = None) -> str:
        """Run the one-time interactive flow. Returns a human-readable result.

        `ui` defaults to the console, so the CLI needs no argument.
        """
        ...

    def status(self) -> tuple[str, str | None]:
        """Return ("ok"|"needs_auth"|"error", detail) without any network round-trip
        that would require user interaction."""
        ...
