"""Canonical registry of MCP tools that can be allowed/forbidden per account.

Kept separate from server.py so config.py can validate `disabled_tools`
against it without importing the MCP tool definitions themselves. Adding a
future tool (e.g. a write action) means appending it here - config validation
and the server-side guard both derive from this tuple.

`list_accounts` is intentionally excluded: it has no per-account scope.
"""

from __future__ import annotations

TOOL_NAMES: tuple[str, ...] = (
    "list_folders",
    "list_messages",
    "search_messages",
    "read_message",
    "get_attachment",
)

TOOL_LABELS: dict[str, str] = {
    "list_folders": "List folders",
    "list_messages": "Browse messages",
    "search_messages": "Search messages",
    "read_message": "Read a message",
    "get_attachment": "Download attachments",
}

assert set(TOOL_LABELS) == set(TOOL_NAMES)
