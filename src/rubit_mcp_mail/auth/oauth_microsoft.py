"""MSAL device-code auth for Outlook.com / Microsoft 365 IMAP.

Microsoft retired basic auth for Outlook.com, so OAuth2 + SASL XOAUTH2 is the
only remaining way in. The interactive device-code flow runs once from the CLI;
the resulting refresh token lives in the SecretStore and the server thereafter
only ever acquires tokens silently.
"""

from __future__ import annotations

import logging

import msal
from imapclient import IMAPClient
from imapclient.exceptions import LoginError

from ..config import Account
from ..secrets import SecretStore
from .base import NeedsAuthError

log = logging.getLogger(__name__)


class MicrosoftDeviceCodeAuth:
    def __init__(self, account: Account, store: SecretStore) -> None:
        self._account = account
        self._store = store
        self.secret_key = f"msal-cache:{account.name}"
        self._oauth = account.profile.oauth
        if self._oauth is None:
            raise ValueError(
                f"Provider {account.provider!r} has no OAuth configuration."
            )

    # -- MSAL plumbing ---------------------------------------------------
    def _load_cache(self) -> msal.SerializableTokenCache:
        cache = msal.SerializableTokenCache()
        if blob := self._store.get(self.secret_key):
            cache.deserialize(blob)
        return cache

    def _save_cache(self, cache: msal.SerializableTokenCache) -> None:
        if cache.has_state_changed:
            self._store.set(self.secret_key, cache.serialize())

    def _app(self, cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
        return msal.PublicClientApplication(
            client_id=self._account.client_id,
            authority=self._oauth.authority,
            token_cache=cache,
        )

    def _token_silent(self) -> tuple[str | None, str]:
        """Acquire an access token without user interaction.

        Returns (token, reason). When the token is None the reason says which
        step failed, because "not authenticated" has several very different
        causes - most confusingly a token that exists but sits in a keyring
        this process cannot reach.
        """
        blob = self._store.get(self.secret_key)
        if not blob:
            reason = f"no token cache in {self._store.backend_name}"
            if hint := self._store.unavailable_reason:
                reason += (
                    f". The keyring is not being used here ({hint}); if you ran "
                    f"`rubit-mcp-mail auth {self._account.name}` from a desktop terminal "
                    "the token is in the keyring and invisible to this process"
                )
            log.debug("account %s: %s", self._account.name, reason)
            return None, reason

        cache = msal.SerializableTokenCache()
        cache.deserialize(blob)
        app = self._app(cache)
        accounts = [
            a for a in app.get_accounts()
            if a.get("username", "").lower() == self._account.email.lower()
        ]
        if not accounts:
            known = ", ".join(sorted(a.get("username", "?") for a in app.get_accounts()))
            return None, (
                f"the token cache holds no entry for {self._account.email}"
                + (f" (it has: {known})" if known else "")
            )

        result = app.acquire_token_silent(self._oauth.scopes, account=accounts[0])
        self._save_cache(cache)
        if result and "access_token" in result:
            log.debug("account %s: acquired token silently", self._account.name)
            return result["access_token"], "ok"
        detail = ""
        if isinstance(result, dict):
            detail = result.get("error_description") or result.get("error") or ""
        return None, f"refresh failed{f': {detail}' if detail else ''}"

    # -- AuthStrategy ----------------------------------------------------
    def login(self, client: IMAPClient) -> None:
        token, reason = self._token_silent()
        if not token:
            raise NeedsAuthError(self._account.name, reason)
        try:
            client.oauth2_login(self._account.email, token, mech="XOAUTH2")
        except LoginError as exc:
            # A rejected-but-valid-looking token usually means the Azure app is
            # missing the IMAP permission, which is worth saying out loud.
            raise NeedsAuthError(
                self._account.name,
                f"server rejected the OAuth token: {exc}. Check that your Azure app has "
                "the delegated 'IMAP.AccessAsUser.All' permission under "
                "'Office 365 Exchange Online'",
            ) from exc

    def interactive_setup(self) -> str:
        cache = self._load_cache()
        app = self._app(cache)

        flow = app.initiate_device_flow(scopes=self._oauth.scopes)
        if "user_code" not in flow:
            error = flow.get("error_description") or flow.get("error") or str(flow)
            raise RuntimeError(
                f"Could not start the device-code flow: {error}\n"
                "Most often this means the Azure app registration does not have "
                "'Allow public client flows' enabled."
            )

        print()
        print(flow["message"])
        print()
        print("Waiting for you to complete sign-in in the browser...")

        result = app.acquire_token_by_device_flow(flow)  # blocks until done/expired
        self._save_cache(cache)

        if "access_token" not in result:
            error = result.get("error_description") or result.get("error") or str(result)
            raise RuntimeError(f"Sign-in failed: {error}")

        signed_in = (result.get("id_token_claims") or {}).get("preferred_username")
        if signed_in and signed_in.lower() != self._account.email.lower():
            return (
                f"Warning: you signed in as {signed_in}, but the account is configured "
                f"with email {self._account.email}. Update `email` in the config to match, "
                "or IMAP login will fail."
            )
        return f"Signed in as {signed_in or self._account.email}. Token cached."

    def status(self) -> tuple[str, str | None]:
        try:
            token, reason = self._token_silent()
        except Exception as exc:  # noqa: BLE001 - report, never crash the tool listing
            return "error", str(exc)
        return ("ok", None) if token else ("needs_auth", reason)
