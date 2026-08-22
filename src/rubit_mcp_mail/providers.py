"""Provider profiles.

A profile is pure data: where the IMAP server lives and how to authenticate to
it. Supporting a new provider should mean adding an entry here, not writing a
new backend.
"""

from __future__ import annotations

from pydantic import BaseModel


class MicrosoftOAuth(BaseModel):
    # /common accepts both personal Microsoft accounts and work/school ones.
    authority: str = "https://login.microsoftonline.com/common"
    # Full resource-qualified scope; the bare 'IMAP.AccessAsUser.All' is rejected.
    # MSAL adds offline_access/openid/profile itself, so they must not be listed.
    scopes: list[str] = ["https://outlook.office.com/IMAP.AccessAsUser.All"]


class ImapProfile(BaseModel):
    auth: str
    host: str | None = None
    port: int = 993
    ssl: bool = True
    oauth: MicrosoftOAuth | None = None
    # Whether the account config must supply its own host.
    requires_host: bool = False


PROFILES: dict[str, ImapProfile] = {
    "outlook": ImapProfile(
        auth="oauth_microsoft",
        host="outlook.office365.com",
        port=993,
        ssl=True,
        oauth=MicrosoftOAuth(),
    ),
    # Anything else that speaks IMAP: Gmail, Fastmail, iCloud, self-hosted.
    "generic": ImapProfile(auth="password", requires_host=True),
}


def get_profile(name: str) -> ImapProfile:
    try:
        return PROFILES[name]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown provider {name!r}. Known providers: {known}") from None
