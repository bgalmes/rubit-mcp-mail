"""Registering the server with Claude Desktop and Claude Code.

Both halves touch something we don't own - another application's config file,
and another application's CLI - so they live here, behind small functions the
setup wizard can call and the tests can fake, rather than inline in the wizard.

Registration is written to be safe to repeat: the wizard is meant to be re-run
to add a second account or repair a broken setup, and re-running must not
duplicate entries or discard anything the user (or another tool) put there.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: Name the server is registered under in both clients.
SERVER_NAME = "rubit-mail"


# -- Claude Code ---------------------------------------------------------
def claude_code_available() -> bool:
    return shutil.which("claude") is not None


def register_claude_code(server_path: Path, *, name: str = SERVER_NAME) -> tuple[bool, str]:
    """Register `server_path` with Claude Code. Returns (ok, output).

    Removes any existing registration first and ignores the result: `claude mcp
    add` fails when the name is already taken, and remove-then-add is idempotent
    without having to match on the CLI's error text, which we don't control.
    """
    subprocess.run(
        ["claude", "mcp", "remove", name, "--scope", "user"],
        capture_output=True,
        text=True,
        check=False,
    )
    result = subprocess.run(
        ["claude", "mcp", "add", name, "--scope", "user", "--", str(server_path), "serve"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


# -- Claude Desktop ------------------------------------------------------
def claude_desktop_config_path() -> Path:
    """Where Claude Desktop keeps claude_desktop_config.json."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Claude" / "claude_desktop_config.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Claude" / "claude_desktop_config.json"


def claude_desktop_detected() -> bool:
    """Whether Claude Desktop looks installed.

    The directory is created on first run, so its absence is a reasonable "not
    installed"; the config file itself may legitimately not exist yet.
    """
    return claude_desktop_config_path().parent.is_dir()


def desktop_entry(server_path: Path, *, needs_no_keyring: bool) -> dict:
    """Build our one `mcpServers` entry.

    On Linux, Claude Desktop launches servers with a stripped environment, so
    the desktop keyring is unreachable and a token stored there would be
    invisible to the server. Rather than pinning this session's
    DBUS_SESSION_BUS_ADDRESS/XDG_RUNTIME_DIR into a config file that outlives
    the session, point both sides at the file-based secret store. On Windows
    the Credential Manager is reachable from every process, so no env block is
    needed at all.
    """
    entry: dict = {"command": str(server_path), "args": ["serve"]}
    if needs_no_keyring and sys.platform != "win32":
        entry["env"] = {"RUBIT_MCP_MAIL_NO_KEYRING": "1"}
    return entry


def register_claude_desktop(
    server_path: Path,
    *,
    needs_no_keyring: bool,
    config_path: Path | None = None,
    name: str = SERVER_NAME,
) -> Path:
    """Merge our entry into claude_desktop_config.json, leaving the rest alone.

    Only `mcpServers[name]` is written: other servers, and any other top-level
    key Claude Desktop keeps in there, survive verbatim. The file belongs to
    another application, so it is replaced atomically - a half-written config
    would break every server it lists, not just ours.
    """
    path = config_path or claude_desktop_config_path()

    document: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text("utf-8"))
        except ValueError as exc:
            raise ValueError(
                f"{path} is not valid JSON ({exc}). Fix or remove it, then re-run setup."
            ) from None
        if not isinstance(loaded, dict):
            raise ValueError(f"{path} does not contain a JSON object. Fix or remove it.")
        document = loaded

    servers = document.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[name] = desktop_entry(server_path, needs_no_keyring=needs_no_keyring)
    document["mcpServers"] = servers

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2) + "\n"
    # Write beside the target so os.replace stays on one filesystem.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rubit-mcp-mail-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path
