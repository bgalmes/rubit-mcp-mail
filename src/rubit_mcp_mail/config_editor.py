"""Every write to config.toml goes through this module.

Two properties matter here, and they are why this is tomlkit rather than
`tomllib` plus a serializer: an edit must leave the user's own comments, key
order and spacing exactly as it found them, and a rejected edit must leave the
file untouched. `save_document` gets the second one by writing a temp file,
running it through `config.load_config` - the very same parser the CLI and the
server use - and only then replacing the original.

The web form posts one checkbox per (account, tool) pair, named
`enabled__<account>__<tool>`, present in the body only when checked (standard
HTML checkbox semantics). `apply_toggles` turns that into the new
`disabled_tools` list per account.

Write permissions (`allow_write` / `enabled_write_tools`) follow the same
posted-form shape but are opt-in rather than opt-out - see
`apply_write_toggles` and `write_write_permissions` below.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import ValidationError
from tomlkit import TOMLDocument

from .config import Account, first_error, load_config
from .permissions import TOOL_NAMES, WRITE_TOOL_NAMES
from .providers import PROFILES

CHECKBOX_PREFIX = "enabled__"
WRITE_PARENT_PREFIX = "write_allow__"
WRITE_TOOL_PREFIX = "write_tool__"

# An account name is both a TOML bare key and part of the SecretStore key, so
# keep it to characters that need no quoting anywhere.
ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Deliberately lenient: enough to catch an empty or obviously mistyped address,
# not an attempt at RFC 5322.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The account keys the GUI knows how to write. `disabled_tools`, `allow_write`
# and `enabled_write_tools` are deliberately absent: they are owned by the
# permissions page and must survive an account edit.
ACCOUNT_FIELDS = ("provider", "email", "client_id", "host", "port", "ssl")


# -- permissions -------------------------------------------------------------
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
    doc = load_document(path)
    accounts_table = doc.get("accounts")
    for name, disabled in updates.items():
        if accounts_table is None or name not in accounts_table:
            continue
        table = accounts_table[name]
        if disabled:
            table["disabled_tools"] = sorted(disabled)
        else:
            table.pop("disabled_tools", None)
    save_document(path, doc)


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
    doc = load_document(path)
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
    save_document(path, doc)


# -- document I/O ------------------------------------------------------------
def load_document(path: Path) -> TOMLDocument:
    """Parse the config for editing; an absent file edits as an empty document."""
    if not path.exists():
        return tomlkit.document()
    with path.open("r", encoding="utf-8") as fh:
        return tomlkit.parse(fh.read())


def save_document(path: Path, doc: TOMLDocument) -> None:
    """Write `doc` to `path`, but only if `load_config` still accepts the result.

    Validating the rendered file rather than the in-memory edit means the GUI
    can never write something the CLI would then refuse to read. Because the
    check happens on a temp file next to the target, a rejected edit - or a
    crash mid-write - leaves the existing config byte for byte as it was.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    try:
        load_config(tmp)
    except Exception as exc:  # noqa: BLE001 - any rejection is the user's to see
        tmp.unlink(missing_ok=True)
        raise ValueError(str(exc)) from None
    os.replace(tmp, path)


# -- accounts ----------------------------------------------------------------
def _accounts(doc: TOMLDocument) -> Any:
    if "accounts" not in doc:
        doc["accounts"] = tomlkit.table(is_super_table=True)
    return doc["accounts"]


def upsert_account(doc: TOMLDocument, name: str, fields: dict[str, Any]) -> None:
    """Create or update one `[accounts.<name>]` table.

    Only keys present in `fields` are touched, and a key whose value is None or
    empty is removed rather than written blank - so clearing the port field in
    the GUI falls back to the provider default instead of pinning `port = ""`.
    """
    accounts = _accounts(doc)
    if name not in accounts:
        accounts[name] = tomlkit.table()
    table = accounts[name]
    for key in ACCOUNT_FIELDS:
        if key not in fields:
            continue
        value = fields[key]
        if value is None or value == "":
            table.pop(key, None)
        else:
            table[key] = value


def remove_account(doc: TOMLDocument, name: str) -> None:
    accounts = doc.get("accounts")
    if accounts is None:
        return
    accounts.pop(name, None)
    if not accounts:
        doc.pop("accounts", None)


def set_download_dir(doc: TOMLDocument, value: str) -> None:
    if value.strip():
        doc["download_dir"] = value.strip()
    else:
        doc.pop("download_dir", None)


# -- provider overrides ------------------------------------------------------
def _providers(doc: TOMLDocument) -> Any:
    if "providers" not in doc:
        doc["providers"] = tomlkit.table(is_super_table=True)
    return doc["providers"]


def upsert_provider_override(doc: TOMLDocument, name: str, fields: dict[str, Any]) -> None:
    """Write a `[providers.<name>]` table from {host, port, ssl, authority, scopes}.

    Empty values remove their key, and a table left with nothing in it removes
    itself - so the config never accumulates hollow `[providers.x]` headers.
    Whether the keys are actually overridable is not re-checked here:
    `save_document` runs `load_config`, which already applies them through
    `providers.apply_overrides` and rejects the unknown ones.
    """
    providers = _providers(doc)
    if name not in providers:
        providers[name] = tomlkit.table()
    table = providers[name]

    for key in ("host", "port", "ssl"):
        value = fields.get(key)
        if value is None or value == "":
            table.pop(key, None)
        else:
            table[key] = value

    oauth_fields = {
        key: fields.get(key)
        for key in ("authority", "scopes")
        if fields.get(key) not in (None, "", [])
    }
    if oauth_fields:
        if "oauth" not in table:
            table["oauth"] = tomlkit.table()
        oauth = table["oauth"]
        for key in ("authority", "scopes"):
            if key in oauth_fields:
                oauth[key] = oauth_fields[key]
            else:
                oauth.pop(key, None)
        if not oauth:
            table.pop("oauth", None)
    else:
        table.pop("oauth", None)

    if not table:
        remove_provider_override(doc, name)


def remove_provider_override(doc: TOMLDocument, name: str) -> None:
    providers = doc.get("providers")
    if providers is None:
        return
    providers.pop(name, None)
    if not providers:
        doc.pop("providers", None)


# -- validation --------------------------------------------------------------
def validate_account_form(name: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Check and normalise one submitted account form.

    Returns the cleaned field dict ready for `upsert_account`, or raises
    ValueError with a message meant for the user. Provider-specific rules are
    not restated here: the cleaned fields go through `config.Account`, whose
    own validator already phrases them the way `doctor` does.
    """
    name = (name or "").strip()
    if not ACCOUNT_NAME_RE.match(name):
        raise ValueError(
            "The account name must not be empty, and may only contain letters, digits, "
            "dots, dashes and underscores - it names a section in config.toml."
        )

    provider = (fields.get("provider") or "generic").strip()
    if provider not in PROFILES:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown provider {provider!r}. Known providers: {known}")

    email = (fields.get("email") or "").strip()
    if not EMAIL_RE.match(email):
        raise ValueError(f"{email or '(empty)'} does not look like an email address.")

    cleaned: dict[str, Any] = {
        "provider": provider,
        "email": email,
        "client_id": (fields.get("client_id") or "").strip() or None,
        "host": (fields.get("host") or "").strip() or None,
        "port": _clean_port(fields.get("port")),
        "ssl": _clean_ssl(fields.get("ssl")),
    }

    try:
        Account(name=name, **{key: value for key, value in cleaned.items() if value is not None})
    except ValidationError as exc:
        raise ValueError(first_error(exc)) from None
    return cleaned


def _clean_ssl(value: Any) -> bool | None:
    """None means "say nothing and take the provider default"."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "false"):
        return text == "true"
    raise ValueError(f"SSL must be true or false, not {value!r}.")


def _clean_port(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        port = int(str(value).strip())
    except ValueError:
        raise ValueError(f"Port must be a whole number, not {value!r}.") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"Port must be between 1 and 65535, not {port}.")
    return port
