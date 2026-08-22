"""Ties config + auth + backend together and keeps one connection per account."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .auth import build_auth
from .backends import ImapBackend
from .config import Account, Config, load_config
from .secrets import SecretStore


class Session:
    def __init__(self, config: Config | None = None, store: SecretStore | None = None) -> None:
        self._config = config
        self._store = store or SecretStore()
        self._backends: dict[str, ImapBackend] = {}

    @property
    def config(self) -> Config:
        if self._config is None:
            self._config = load_config()
        return self._config

    def account(self, name: str | None) -> Account:
        return self.config.account(name)

    def auth_for(self, account: Account):
        return build_auth(account, self._store)

    def backend(self, name: str | None) -> ImapBackend:
        account = self.account(name)
        if account.name not in self._backends:
            self._backends[account.name] = ImapBackend(account, self.auth_for(account))
        return self._backends[account.name]

    def close(self) -> None:
        for backend in self._backends.values():
            backend.close()
        self._backends.clear()

    # -- attachments -----------------------------------------------------
    def download_path(self, filename: str) -> Path:
        """Resolve a safe destination inside the configured download directory."""
        directory = self.config.download_dir.expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / safe_filename(filename)

        # Belt and braces: a crafted filename must not escape the directory.
        resolved = target.resolve()
        if not resolved.is_relative_to(directory.resolve()):
            raise ValueError("Refusing to write outside the download directory.")

        # Never clobber an existing file.
        if resolved.exists():
            stem, suffix = resolved.stem, resolved.suffix
            for n in range(1, 1000):
                candidate = resolved.with_name(f"{stem}-{n}{suffix}")
                if not candidate.exists():
                    return candidate
        return resolved


def safe_filename(name: str) -> str:
    """Strip anything that could steer the write somewhere unintended."""
    name = unicodedata.normalize("NFKC", name)
    name = name.replace("\\", "/").split("/")[-1]  # drop any path component
    name = re.sub(r"[\x00-\x1f]", "", name).strip().lstrip(".")
    name = re.sub(r'[<>:"|?*]', "_", name)
    return name[:180] or "attachment"
