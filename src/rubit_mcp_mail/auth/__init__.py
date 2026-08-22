"""Authentication strategies for IMAP connections."""

from __future__ import annotations

from ..config import Account
from ..secrets import SecretStore
from .base import AuthStrategy, NeedsAuthError
from .oauth_microsoft import MicrosoftDeviceCodeAuth
from .password import PasswordAuth

__all__ = [
    "AuthStrategy",
    "NeedsAuthError",
    "MicrosoftDeviceCodeAuth",
    "PasswordAuth",
    "build_auth",
]

_STRATEGIES = {
    "password": PasswordAuth,
    "oauth_microsoft": MicrosoftDeviceCodeAuth,
}


def build_auth(account: Account, store: SecretStore) -> AuthStrategy:
    kind = account.profile.auth
    try:
        cls = _STRATEGIES[kind]
    except KeyError:
        raise ValueError(f"Unknown auth strategy {kind!r}") from None
    return cls(account, store)
