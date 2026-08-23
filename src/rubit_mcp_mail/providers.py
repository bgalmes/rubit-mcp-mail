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


_OVERRIDABLE = {"host", "port", "ssl"}
_OVERRIDABLE_OAUTH = {"authority", "scopes"}


def apply_overrides(profile: ImapProfile, overrides: dict) -> ImapProfile:
    """Layer a raw {host, port, ssl, oauth: {authority, scopes}} dict onto a profile.

    Lets the endpoint strings above be corrected locally (e.g. if Microsoft
    changes its IMAP host or OAuth authority) without editing this file.
    Unknown keys raise rather than being silently ignored, so a typo in the
    user's config is caught immediately instead of quietly doing nothing.
    Never mutates `profile` - PROFILES entries are shared, module-level
    singletons reused by every call.
    """
    if not overrides:
        return profile

    overrides = dict(overrides)
    oauth_overrides = overrides.pop("oauth", None)
    unknown = set(overrides) - _OVERRIDABLE
    if unknown:
        raise ValueError(f"Unknown provider override key(s): {', '.join(sorted(unknown))}")

    update = dict(overrides)
    if oauth_overrides:
        if profile.oauth is None:
            raise ValueError("This provider has no OAuth configuration to override")
        unknown_oauth = set(oauth_overrides) - _OVERRIDABLE_OAUTH
        if unknown_oauth:
            raise ValueError(
                f"Unknown provider oauth override key(s): {', '.join(sorted(unknown_oauth))}"
            )
        update["oauth"] = profile.oauth.model_copy(update=dict(oauth_overrides))

    return profile.model_copy(update=update)
