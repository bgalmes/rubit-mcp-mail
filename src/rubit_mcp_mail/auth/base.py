from __future__ import annotations

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
            f"Account {account!r} is not authenticated{suffix}. "
            f"Run: rubit-mcp-mail auth {account}"
        )


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

    def interactive_setup(self) -> str:
        """Run the one-time interactive flow. Returns a human-readable result."""

    def status(self) -> tuple[str, str | None]:
        """Return ("ok"|"needs_auth"|"error", detail) without any network round-trip
        that would require user interaction."""
