"""Config loading from ~/.config/rubit-mcp-mail/config.toml.

Deliberately contains no secrets - only where mailboxes live and which
provider profile to use. Credentials come from SecretStore.
"""

from __future__ import annotations

import os
from pathlib import Path

import tomllib
from pydantic import BaseModel, Field, PrivateAttr, ValidationError, model_validator

from .providers import ImapProfile, apply_overrides, get_profile


class Account(BaseModel):
    name: str
    provider: str = "generic"
    email: str
    # Only meaningful for OAuth providers.
    client_id: str | None = None
    # Override or supply the server for the generic profile.
    host: str | None = None
    port: int | None = None
    ssl: bool | None = None
    # Set by load_config() from the config's top-level [providers.*] tables;
    # empty for accounts built directly (e.g. in tests).
    _provider_overrides: dict = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def _check_against_profile(self) -> Account:
        profile = get_profile(self.provider)
        if profile.requires_host and not (self.host or profile.host):
            raise ValueError(
                f"Account {self.name!r} uses the {self.provider!r} provider, "
                'which needs an explicit `host` (e.g. host = "imap.fastmail.com").'
            )
        if profile.auth == "oauth_microsoft" and not self.client_id:
            raise ValueError(
                f"Account {self.name!r} needs a `client_id` - the Application (client) ID "
                "of your Azure app registration. See the README for the setup steps."
            )
        return self

    @property
    def profile(self) -> ImapProfile:
        """Provider defaults, with [providers.*] and then per-account overrides applied."""
        profile = apply_overrides(get_profile(self.provider), self._provider_overrides)
        return profile.model_copy(
            update={
                "host": self.host or profile.host,
                "port": self.port if self.port is not None else profile.port,
                "ssl": self.ssl if self.ssl is not None else profile.ssl,
            }
        )


class Config(BaseModel):
    download_dir: Path = Field(default=Path.home() / "Downloads" / "rubit-mcp-mail")
    accounts: dict[str, Account] = Field(default_factory=dict)
    # Raw [providers.<name>] tables from config.toml: local overrides for the
    # compiled-in endpoint strings in providers.py, so a Microsoft (or other
    # provider) change doesn't require a new release - only a local edit.
    providers: dict[str, dict] = Field(default_factory=dict)

    def account(self, name: str | None) -> Account:
        """Resolve an account by name, defaulting when only one is configured."""
        if not self.accounts:
            raise ValueError(f"No accounts configured. Create {config_path()} - see the README.")
        if name is None:
            if len(self.accounts) == 1:
                return next(iter(self.accounts.values()))
            known = ", ".join(sorted(self.accounts))
            raise ValueError(f"Several accounts configured; pass one of: {known}")
        try:
            return self.accounts[name]
        except KeyError:
            known = ", ".join(sorted(self.accounts))
            raise ValueError(f"Unknown account {name!r}. Configured: {known}") from None


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    msg = err["msg"].removeprefix("Value error, ")
    loc = ".".join(str(part) for part in err["loc"])
    return f"{msg} (at {loc})" if loc and "Account" not in msg else msg


def config_path() -> Path:
    if override := os.environ.get("RUBIT_MCP_MAIL_CONFIG"):
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "rubit-mcp-mail" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        raise FileNotFoundError(f"No config at {path}. Create it - see the README for a template.")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    providers_raw = raw.pop("providers", {}) or {}
    for name, overrides in providers_raw.items():
        try:
            apply_overrides(get_profile(name), overrides)
        except ValueError as exc:
            raise ValueError(f"In [providers.{name}] of {path}: {exc}") from None

    accounts_raw = raw.pop("accounts", {}) or {}
    accounts = {}
    for name, body in accounts_raw.items():
        try:
            account = Account(name=name, **body)
        except ValidationError as exc:
            # Surface our own validator text; pydantic's wrapper buries the
            # setup guidance under a URL the user does not need.
            raise ValueError(_first_error(exc)) from None
        account._provider_overrides = providers_raw.get(account.provider, {})
        accounts[name] = account
    download_dir = Path(
        str(raw.pop("download_dir", Path.home() / "Downloads" / "rubit-mcp-mail"))
    ).expanduser()
    if raw:
        unknown = ", ".join(sorted(raw))
        raise ValueError(f"Unknown key(s) in {path}: {unknown}")
    return Config(download_dir=download_dir, accounts=accounts, providers=providers_raw)
