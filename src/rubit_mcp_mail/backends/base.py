"""The backend contract.

Only ImapBackend implements this today. It exists so that a native Graph or
Gmail-API backend can be dropped in without the tool layer changing, which is
the escape hatch if a provider ever withdraws IMAP access.

Every method is read-only by contract, with two deliberate exceptions:
`mark_read` and `move_message`. Both are gated at the tool layer by
Account.can_write and are off by default - see permissions.WRITE_TOOL_NAMES.
No implementation may otherwise set flags, move, delete, append, or expunge.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from ..mime import DEFAULT_MAX_CHARS
from ..models import Folder, Message, MessageSummary


@runtime_checkable
class MailBackend(Protocol):
    def list_folders(self) -> list[Folder]: ...

    def list_messages(
        self,
        folder: str = "inbox",
        limit: int = 25,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[MessageSummary]: ...

    def search_messages(
        self,
        folder: str = "inbox",
        text: str | None = None,
        from_: str | None = None,
        subject: str | None = None,
        since: date | None = None,
        before: date | None = None,
        unread_only: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[MessageSummary]: ...

    def read_message(self, handle: str, max_chars: int = DEFAULT_MAX_CHARS) -> Message: ...

    def fetch_attachment(self, handle: str, part_id: str) -> tuple[str, bytes]: ...

    def mark_read(self, handle: str) -> None: ...

    def move_message(self, handle: str, folder: str) -> str: ...

    def close(self) -> None: ...
