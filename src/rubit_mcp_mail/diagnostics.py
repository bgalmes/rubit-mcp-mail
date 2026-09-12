"""The `doctor` checks, as data.

Splitting the checks from the printing means the CLI and the GUI diagnose an
account the same way and, more importantly, report a failure in the same words:
there is exactly one place that decides what "not authenticated" means or how a
connection error is phrased.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, config_path, load_config
from .models import Folder
from .secrets import SecretStore
from .session import Session


@dataclass
class AccountReport:
    """One account's health: config, credential, and (optionally) connectivity."""

    name: str
    provider: str = ""
    email: str = ""
    host: str | None = None
    port: int | None = None
    ssl: bool | None = None
    #: "ok" | "needs_auth" | "error", straight from the AuthStrategy.
    auth_state: str = ""
    auth_detail: str | None = None
    #: Set when the account could not be checked at all - unresolvable config,
    #: or a connection that raised.
    error: str | None = None
    capabilities: list[str] = field(default_factory=list)
    folders: list[Folder] = field(default_factory=list)
    #: False when `connect=False` asked for a credential check only.
    connected: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and self.auth_state == "ok"


@dataclass
class Report:
    config_path: Path
    #: True when there is no config file at all - the first-run case, which
    #: wants a "create one" path rather than an error.
    missing_config: bool = False
    #: Set when the file exists but could not be loaded.
    config_error: str | None = None
    download_dir: Path | None = None
    #: {provider name: overridden keys}, oauth sub-keys flattened to "oauth.x".
    provider_overrides: dict[str, list[str]] = field(default_factory=dict)
    secrets_backend: str = ""
    #: Why the keyring is not in use, when it is not.
    secrets_warning: str | None = None
    accounts: list[AccountReport] = field(default_factory=list)

    @property
    def failures(self) -> int:
        return sum(1 for account in self.accounts if not account.ok)


def override_keys(overrides: dict) -> list[str]:
    """Flatten one [providers.*] table to the key names doctor lists."""
    keys = []
    for key, value in overrides.items():
        if key == "oauth" and isinstance(value, dict):
            keys.extend(f"oauth.{sub}" for sub in value)
        else:
            keys.append(key)
    return sorted(keys)


def check_account(session: Session, name: str, *, connect: bool = True) -> AccountReport:
    """Check one account. With `connect`, also opens IMAP and lists folders.

    Never raises: every failure becomes a field on the report, because the
    caller is either printing a diagnosis or rendering one.
    """
    report = AccountReport(name=name)
    try:
        account = session.account(name)
    except Exception as exc:  # noqa: BLE001 - unknown/invalid account is a finding
        report.error = str(exc)
        return report

    profile = account.profile
    report.provider = account.provider
    report.email = account.email
    report.host, report.port, report.ssl = profile.host, profile.port, profile.ssl
    report.auth_state, report.auth_detail = session.auth_for(account).status()

    if report.auth_state != "ok" or not connect:
        return report

    backend = session.backend(name)
    try:
        report.capabilities = list(backend.capabilities())
        report.folders = list(backend.list_folders())
        report.connected = True
    except Exception as exc:  # noqa: BLE001 - report it, don't crash the run
        report.error = f"{type(exc).__name__}: {exc}"
    finally:
        backend.close()
    return report


def run_doctor(
    names: list[str] | None = None,
    *,
    connect: bool = True,
    config: Config | None = None,
    store: SecretStore | None = None,
) -> Report:
    """Check the config file and, unless `names` narrows it, every account."""
    path = config_path()
    report = Report(config_path=path)

    if config is None:
        try:
            config = load_config()
        except FileNotFoundError:
            report.missing_config = True
            return report
        except Exception as exc:  # noqa: BLE001 - a bad config is the finding
            report.config_error = str(exc)
            return report

    report.download_dir = config.download_dir
    report.provider_overrides = {
        name: override_keys(overrides) for name, overrides in sorted(config.providers.items())
    }

    store = store or SecretStore()
    report.secrets_backend = store.backend_name
    report.secrets_warning = store.unavailable_reason

    session = Session(config=config, store=store)
    for name in names if names is not None else list(config.accounts):
        report.accounts.append(check_account(session, name, connect=connect))
    return report
