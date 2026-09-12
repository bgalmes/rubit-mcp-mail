"""MSAL device-code auth for Outlook.com / Microsoft 365 IMAP.

Microsoft retired basic auth for Outlook.com, so OAuth2 + SASL XOAUTH2 is the
only remaining way in. The interactive device-code flow runs once from the CLI;
the resulting refresh token lives in the SecretStore and the server thereafter
only ever acquires tokens silently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import msal
from imapclient import IMAPClient
from imapclient.exceptions import LoginError

from ..config import Account
from ..providers import MicrosoftOAuth
from ..secrets import SecretStore
from .base import AuthUI, ConsoleAuthUI, NeedsAuthError

log = logging.getLogger(__name__)


@dataclass
class DeviceFlow:
    """A started device-code flow, waiting for the user to type the code.

    Carries the MSAL app and cache alongside the flow dict because the blocking
    half of the handshake must finish into the *same* cache the first half
    created, whether the two halves are a print and a getpass or two HTTP
    requests.
    """

    flow: dict
    app: msal.PublicClientApplication
    cache: msal.SerializableTokenCache

    @property
    def message(self) -> str:
        """MSAL's own instructions: the code, and where to type it."""
        return self.flow.get("message", "")

    @property
    def user_code(self) -> str:
        return self.flow.get("user_code", "")

    @property
    def verification_uri(self) -> str:
        return self.flow.get("verification_uri") or self.flow.get("verification_url") or ""


class MicrosoftDeviceCodeAuth:
    def __init__(self, account: Account, store: SecretStore) -> None:
        self._account = account
        self._store = store
        self.secret_key = f"msal-cache:{account.name}"
        oauth = account.profile.oauth
        if oauth is None:
            raise ValueError(f"Provider {account.provider!r} has no OAuth configuration.")
        self._oauth: MicrosoftOAuth = oauth

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
            a
            for a in app.get_accounts()
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

    def begin_device_flow(self) -> DeviceFlow:
        """Ask Microsoft for a device code. Returns immediately; nothing blocks yet."""
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
        return DeviceFlow(flow=flow, app=app, cache=cache)

    def complete_device_flow(self, started: DeviceFlow) -> str:
        """Block until the user finishes signing in (or the code expires)."""
        result = started.app.acquire_token_by_device_flow(started.flow)
        self._save_cache(started.cache)

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

    def interactive_setup(self, ui: AuthUI | None = None) -> str:
        """Show the code through `ui` (the terminal by default), then block.

        Front ends that cannot block for the whole handshake - the web GUI,
        which has to answer the HTTP request that started it - drive
        `begin_device_flow` and `complete_device_flow` themselves instead.
        """
        ui = ui or ConsoleAuthUI()
        started = self.begin_device_flow()
        ui.device_code(started.flow)
        return self.complete_device_flow(started)

    def status(self) -> tuple[str, str | None]:
        try:
            token, reason = self._token_silent()
        except Exception as exc:  # noqa: BLE001 - report, never crash the tool listing
            return "error", str(exc)
        return ("ok", None) if token else ("needs_auth", reason)
