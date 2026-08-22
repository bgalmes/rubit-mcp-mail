"""Plain IMAP LOGIN, for providers that still accept app passwords.

Note this will NOT work for Outlook.com/Microsoft 365 - Microsoft has retired
basic auth for those. Use the `outlook` provider instead.
"""

from __future__ import annotations

import getpass

from imapclient import IMAPClient
from imapclient.exceptions import LoginError

from ..config import Account
from ..secrets import SecretStore
from .base import NeedsAuthError


class PasswordAuth:
    def __init__(self, account: Account, store: SecretStore) -> None:
        self._account = account
        self._store = store
        self._key = f"password:{account.name}"

    def _password(self) -> str | None:
        # An env var lets you avoid persisting the secret at all.
        import os

        env = os.environ.get(f"RUBIT_MCP_MAIL_PASSWORD_{self._account.name.upper()}")
        return env or self._store.get(self._key)

    def login(self, client: IMAPClient) -> None:
        password = self._password()
        if not password:
            raise NeedsAuthError(self._account.name, "no password stored")
        try:
            client.login(self._account.email, password)
        except LoginError as exc:
            raise NeedsAuthError(self._account.name, f"server rejected login: {exc}") from exc

    def interactive_setup(self) -> str:
        print(f"Account : {self._account.name} <{self._account.email}>")
        print(f"Server  : {self._account.profile.host}:{self._account.profile.port}")
        print("Enter the app password for this mailbox (input is hidden).")
        password = getpass.getpass("App password: ").strip()
        if not password:
            raise ValueError("No password entered; nothing stored.")
        where = self._store.set(self._key, password)
        return f"Password stored in {where}."

    def status(self) -> tuple[str, str | None]:
        if self._password():
            return "ok", None
        return "needs_auth", "no password stored"
