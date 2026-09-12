from pathlib import Path

import pytest

from rubit_mcp_mail.providers import (
    PROFILES,
    THUNDERBIRD_CLIENT_ID,
    apply_overrides,
    get_profile,
)


class TestThunderbirdClientId:
    def test_matches_the_one_documented_in_the_readme(self):
        # The setup wizard offers this as the default, so the constant and the
        # README instructions must not drift apart.
        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        assert THUNDERBIRD_CLIENT_ID in readme


class TestApplyOverrides:
    def test_no_overrides_returns_profile_unchanged(self):
        profile = get_profile("outlook")
        assert apply_overrides(profile, {}) is profile

    def test_overrides_top_level_fields(self):
        profile = apply_overrides(get_profile("outlook"), {"host": "x.example.net", "port": 1993})
        assert (profile.host, profile.port) == ("x.example.net", 1993)

    def test_overrides_nested_oauth_fields(self):
        profile = apply_overrides(
            get_profile("outlook"),
            {"oauth": {"authority": "https://login.example.net/common", "scopes": ["s"]}},
        )
        assert profile.oauth is not None
        assert profile.oauth.authority == "https://login.example.net/common"
        assert profile.oauth.scopes == ["s"]

    def test_unspecified_fields_are_kept(self):
        base = get_profile("outlook")
        profile = apply_overrides(base, {"host": "x.example.net"})
        assert profile.port == base.port
        assert profile.oauth is not None and base.oauth is not None
        assert profile.oauth.authority == base.oauth.authority

    def test_unknown_top_level_key_raises(self):
        with pytest.raises(ValueError, match="Unknown provider override key"):
            apply_overrides(get_profile("outlook"), {"nope": "x"})

    def test_unknown_oauth_key_raises(self):
        with pytest.raises(ValueError, match="Unknown provider oauth override key"):
            apply_overrides(get_profile("outlook"), {"oauth": {"nope": "x"}})

    def test_oauth_override_on_provider_without_oauth_raises(self):
        with pytest.raises(ValueError, match="no OAuth configuration"):
            apply_overrides(get_profile("generic"), {"oauth": {"authority": "x"}})

    def test_does_not_mutate_shared_profile(self):
        base = get_profile("outlook")
        apply_overrides(base, {"host": "x.example.net", "oauth": {"authority": "y"}})
        assert PROFILES["outlook"].host == "outlook.office365.com"
        outlook_oauth = PROFILES["outlook"].oauth
        assert outlook_oauth is not None
        assert outlook_oauth.authority == "https://login.microsoftonline.com/common"
