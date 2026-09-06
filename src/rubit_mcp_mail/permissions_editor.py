"""Pure logic for editing `disabled_tools` in config.toml, kept separate from
webui.py so it's testable without an HTTP server.

The web form posts one checkbox per (account, tool) pair, named
`enabled__<account>__<tool>`, present in the body only when checked (standard
HTML checkbox semantics). `apply_toggles` turns that into the new
`disabled_tools` list per account; `write_disabled_tools` applies it to the
config file on disk while preserving everything else (comments, formatting,
key order) via tomlkit.
"""

from __future__ import annotations

from pathlib import Path

import tomlkit

from .permissions import TOOL_NAMES

CHECKBOX_PREFIX = "enabled__"


def checkbox_name(account: str, tool: str) -> str:
    return f"{CHECKBOX_PREFIX}{account}__{tool}"


def apply_toggles(
    accounts: list[str], posted: dict[str, list[str]]
) -> dict[str, list[str]]:
    """Compute the new disabled_tools list per account from a posted form.

    `posted` is the dict produced by `urllib.parse.parse_qs` - each present
    key maps to a non-empty list of values; an unchecked checkbox simply has
    no key at all.
    """
    result: dict[str, list[str]] = {}
    for account in accounts:
        disabled = [
            tool for tool in TOOL_NAMES if checkbox_name(account, tool) not in posted
        ]
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
