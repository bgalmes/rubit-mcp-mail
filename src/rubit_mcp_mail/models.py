"""Data returned by the backends and, in turn, by the MCP tools."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FolderRole = Literal[
    "inbox", "sent", "drafts", "junk", "trash", "archive", "other"
]


class StaleHandleError(Exception):
    """The folder was renumbered (UIDVALIDITY changed) since the handle was issued."""


class MessageHandle(BaseModel):
    """Opaque, self-describing reference to one message.

    IMAP UIDs are unique only within a folder, and only for as long as that
    folder's UIDVALIDITY is unchanged. Carrying all four parts lets the backend
    detect a renumbered folder instead of silently reading the wrong message.
    """

    account: str
    folder: str
    uidvalidity: int
    uid: int

    def encode(self) -> str:
        raw = f"{self.account}\x1f{self.folder}\x1f{self.uidvalidity}\x1f{self.uid}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, handle: str) -> "MessageHandle":
        padded = handle + "=" * (-len(handle) % 4)
        try:
            raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            account, folder, uidvalidity, uid = raw.split("\x1f")
            return cls(
                account=account,
                folder=folder,
                uidvalidity=int(uidvalidity),
                uid=int(uid),
            )
        except Exception as exc:  # noqa: BLE001 - any malformed input is one error
            raise ValueError(f"Not a valid message handle: {handle!r}") from exc


class Folder(BaseModel):
    name: str = Field(description="Raw server folder name, e.g. 'Junk Email'.")
    role: FolderRole = Field(description="Normalized role, stable across providers.")
    messages: int | None = None
    unseen: int | None = None


class EmailAddress(BaseModel):
    name: str | None = None
    email: str | None = None

    def __str__(self) -> str:
        if self.name and self.email:
            return f"{self.name} <{self.email}>"
        return self.email or self.name or ""


class Attachment(BaseModel):
    part_id: str = Field(description="Pass to get_attachment to download this part.")
    filename: str | None = None
    content_type: str | None = None
    size: int | None = None


class MessageSummary(BaseModel):
    handle: str
    subject: str | None = None
    from_: list[EmailAddress] = Field(default_factory=list, alias="from")
    to: list[EmailAddress] = Field(default_factory=list)
    date: datetime | None = None
    seen: bool = False
    flagged: bool = False
    answered: bool = False
    has_attachments: bool = False
    size: int | None = None
    message_id: str | None = None

    model_config = {"populate_by_name": True}


class Message(MessageSummary):
    cc: list[EmailAddress] = Field(default_factory=list)
    reply_to: list[EmailAddress] = Field(default_factory=list)
    body: str = ""
    body_format: Literal["text", "html-converted", "none"] = "none"
    truncated: bool = False
    attachments: list[Attachment] = Field(default_factory=list)


class AccountStatus(BaseModel):
    name: str
    provider: str
    email: str
    auth: Literal["ok", "needs_auth", "error"]
    detail: str | None = None
