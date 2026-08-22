"""The backend contract.

Only ImapBackend implements this today. It exists so that a native Graph or
Gmail-API backend can be dropped in without the tool layer changing, which is
the escape hatch if a provider ever withdraws IMAP access.

Every method is read-only by contract: no implementation may set flags, move,
delete, append, or expunge.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

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

    def read_message(self, handle: str, max_chars: int = 20_000) -> Message: ...

    def fetch_attachment(self, handle: str, part_id: str) -> tuple[str, bytes]: ...

    def close(self) -> None: ...
