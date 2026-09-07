"""Pure logic for editing `disabled_tools` and write permissions in
config.toml, kept separate from webui.py so it's testable without an HTTP
server.

The web form posts one checkbox per (account, tool) pair, named
`enabled__<account>__<tool>`, present in the body only when checked (standard
HTML checkbox semantics). `apply_toggles` turns that into the new
`disabled_tools` list per account; `write_disabled_tools` applies it to the
config file on disk while preserving everything else (comments, formatting,
key order) via tomlkit.

Write permissions (`allow_write` / `enabled_write_tools`) follow the same
posted-form shape but are opt-in rather than opt-out - see
`apply_write_toggles` and `write_write_permissions` below.
"""

from __future__ import annotations

from pathlib import Path

import tomlkit

from .permissions import TOOL_NAMES, WRITE_TOOL_NAMES

CHECKBOX_PREFIX = "enabled__"
WRITE_PARENT_PREFIX = "write_allow__"
WRITE_TOOL_PREFIX = "write_tool__"


def checkbox_name(account: str, tool: str) -> str:
    return f"{CHECKBOX_PREFIX}{account}__{tool}"


def write_parent_checkbox_name(account: str) -> str:
    return f"{WRITE_PARENT_PREFIX}{account}"


def write_tool_checkbox_name(account: str, tool: str) -> str:
    return f"{WRITE_TOOL_PREFIX}{account}__{tool}"


def apply_toggles(accounts: list[str], posted: dict[str, list[str]]) -> dict[str, list[str]]:
    """Compute the new disabled_tools list per account from a posted form.

    `posted` is the dict produced by `urllib.parse.parse_qs` - each present
    key maps to a non-empty list of values; an unchecked checkbox simply has
    no key at all.
    """
    result: dict[str, list[str]] = {}
    for account in accounts:
        disabled = [tool for tool in TOOL_NAMES if checkbox_name(account, tool) not in posted]
        result[account] = sorted(disabled)
    return result


def write_disabled_tools(path: Path, updates: dict[str, list[str]]) -> None:
    """Update `disabled_tools` for the given accounts in the TOML file at `path`.

    Leaves every other key, comment, and ordering untouched. An empty list
    removes the key entirely rather than writing `disabled_tools = []`.
    """
    with path.open("r", encoding="utf-8") as fh:
        doc = tomlkit.parse(fh.read())

    accounts_table = doc.get("accounts")
    for name, disabled in updates.items():
        if accounts_table is None or name not in accounts_table:
            continue
        table = accounts_table[name]
        if disabled:
            table["disabled_tools"] = sorted(disabled)
        else:
            table.pop("disabled_tools", None)

    with path.open("w", encoding="utf-8") as fh:
        fh.write(tomlkit.dumps(doc))


def apply_write_toggles(
    accounts: list[str], posted: dict[str, list[str]]
) -> dict[str, tuple[bool, list[str]]]:
    """Compute the new (allow_write, enabled_write_tools) per account.

    Opt-in, unlike `apply_toggles`: a write tool is enabled only when its
    checkbox is present in the posted form.
    """
    result: dict[str, tuple[bool, list[str]]] = {}
    for account in accounts:
        allow_write = write_parent_checkbox_name(account) in posted
        enabled = sorted(
            tool for tool in WRITE_TOOL_NAMES if write_tool_checkbox_name(account, tool) in posted
        )
        result[account] = (allow_write, enabled)
    return result


def write_write_permissions(path: Path, updates: dict[str, tuple[bool, list[str]]]) -> None:
    """Update `allow_write`/`enabled_write_tools` for the given accounts.

    Same preserve-everything-else approach as `write_disabled_tools`.
    `allow_write` is omitted when False (its default) and
    `enabled_write_tools` when empty.
    """
    with path.open("r", encoding="utf-8") as fh:
        doc = tomlkit.parse(fh.read())

    accounts_table = doc.get("accounts")
    for name, (allow_write, enabled) in updates.items():
        if accounts_table is None or name not in accounts_table:
            continue
        table = accounts_table[name]
        if allow_write:
            table["allow_write"] = True
        else:
            table.pop("allow_write", None)
        if enabled:
            table["enabled_write_tools"] = enabled
        else:
            table.pop("enabled_write_tools", None)

    with path.open("w", encoding="utf-8") as fh:
        fh.write(tomlkit.dumps(doc))
