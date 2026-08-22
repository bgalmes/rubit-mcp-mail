"""Secret storage: OS keyring when available, 0600 file otherwise.

Holds IMAP passwords and the MSAL token cache. Nothing here is ever logged.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE = "rubit-mcp-mail"


def _fallback_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "rubit-mcp-mail" / "secrets.json"


class SecretStore:
    """Get/set/delete named secrets, transparently choosing a backend.

    The keyring package raises if no usable backend is present (common on
    headless boxes), so every call falls back to an owner-only file.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _fallback_path()

    # -- keyring ---------------------------------------------------------
    def _keyring(self):
        if os.environ.get("RUBIT_MCP_MAIL_NO_KEYRING"):
            return None
        try:
            import keyring
            from keyring.backends import fail

            backend = keyring.get_keyring()
            if isinstance(backend, fail.Keyring):
                return None
            return keyring
        except Exception:  # noqa: BLE001 - any keyring problem means "use the file"
            return None

    # -- file ------------------------------------------------------------
    def _read_file(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text("utf-8"))
        except (OSError, ValueError):
            log.warning("Could not read secret file %s; treating as empty", self._path)
            return {}

    def _write_file(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self._path.parent, 0o700)
        # Create with 0600 from the start so the secret is never briefly world-readable.
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    # -- public ----------------------------------------------------------
    def get(self, key: str) -> str | None:
        kr = self._keyring()
        if kr is not None:
            try:
                value = kr.get_password(SERVICE, key)
                if value is not None:
                    return value
            except Exception:  # noqa: BLE001
                log.debug("keyring read failed for %s; falling back to file", key)
        return self._read_file().get(key)

    def set(self, key: str, value: str) -> str:
        """Store the secret. Returns the backend used, for `doctor` output."""
        kr = self._keyring()
        if kr is not None:
            try:
                kr.set_password(SERVICE, key, value)
                return "keyring"
            except Exception:  # noqa: BLE001
                log.debug("keyring write failed for %s; falling back to file", key)
        data = self._read_file()
        data[key] = value
        self._write_file(data)
        return f"file ({self._path})"

    def delete(self, key: str) -> None:
        kr = self._keyring()
        if kr is not None:
            try:
                kr.delete_password(SERVICE, key)
            except Exception:  # noqa: BLE001
                pass
        data = self._read_file()
        if data.pop(key, None) is not None:
            self._write_file(data)
