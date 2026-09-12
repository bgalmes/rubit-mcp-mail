"""End-to-end tests for the config GUI, driven over real HTTP.

The client below behaves like a browser: it keeps the session cookie, sends an
Origin on posts, and follows redirects - so what these tests exercise is the
same path a user's browser takes, security layer included.
"""

import http.client
import threading
from urllib.parse import urlencode

import pytest

from rubit_mcp_mail.config import load_config
from rubit_mcp_mail.secrets import SecretStore
from rubit_mcp_mail.webui import make_server

CONFIG = """# a hand-written comment that must survive
download_dir = "~/Downloads/rubit-mcp-mail"

[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "abc"

[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
"""

TOOLS = ("list_folders", "list_messages", "search_messages", "read_message", "get_attachment")


class Browser:
    """Minimal cookie-keeping HTTP client for one running server."""

    def __init__(self, server, authorise=True):
        self.port = server.server_port
        self.token = server.token
        self.cookie = None
        if authorise:
            self.get(f"/?t={self.token}", follow=False)

    def request(self, method, path, form=None, follow=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        sent = {"Host": f"127.0.0.1:{self.port}"}
        if self.cookie:
            sent["Cookie"] = self.cookie
        body = None
        if form is not None:
            body = urlencode(form, doseq=True)
            sent["Content-Type"] = "application/x-www-form-urlencoded"
            sent["Origin"] = f"http://127.0.0.1:{self.port}"
        sent.update(headers or {})
        conn.request(method, path, body=body, headers=sent)
        response = conn.getresponse()
        text = response.read().decode()
        if set_cookie := response.getheader("Set-Cookie"):
            self.cookie = set_cookie.split(";")[0]
        location = response.getheader("Location")
        conn.close()
        if follow and response.status == 303 and location:
            return self.request("GET", location)
        return response.status, text, location

    def get(self, path, follow=True, headers=None):
        return self.request("GET", path, follow=follow, headers=headers)

    def post(self, path, form, follow=True, headers=None):
        return self.request("POST", path, form=form, follow=follow, headers=headers)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Config file, secret store and keyring setting all pointed at tmp_path."""
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("RUBIT_MCP_MAIL_CONFIG", str(path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
    return path


@pytest.fixture
def server(env):
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def browser(server):
    return Browser(server)


class TestAccessControl:
    def test_no_token_is_refused(self, server):
        status, body, _ = Browser(server, authorise=False).get("/", follow=False)
        assert status == 403
        assert "token" in body

    def test_wrong_token_is_refused(self, server):
        status, _, _ = Browser(server, authorise=False).get("/?t=nope", follow=False)
        assert status == 403

    def test_token_is_exchanged_for_a_cookie(self, server):
        client = Browser(server, authorise=False)
        status, _, location = client.get(f"/?t={server.token}", follow=False)
        assert status == 303 and location == "/"
        assert client.cookie and server.token in client.cookie
        assert client.get("/")[0] == 200

    def test_token_handshake_keeps_the_deep_link(self, server):
        """`rubit-mcp-mail permissions` opens /permissions?t=... directly."""
        client = Browser(server, authorise=False)
        _, _, location = client.get(f"/permissions?t={server.token}", follow=False)
        assert location == "/permissions"
        assert "Read a message" in client.get("/permissions")[1]

    def test_non_loopback_host_is_refused(self, browser):
        status, _, _ = browser.get("/", headers={"Host": "mail.example.com"})
        assert status == 403

    def test_cross_origin_post_is_refused(self, browser, env):
        original = env.read_text()
        status, _, _ = browser.post(
            "/download-dir",
            {"download_dir": "~/Elsewhere"},
            headers={"Origin": "http://evil.example.com"},
        )
        assert status == 403
        assert env.read_text() == original


class TestOverview:
    def test_lists_accounts_and_their_sign_in_state(self, browser):
        status, body, _ = browser.get("/")
        assert status == 200
        assert "outlook" in body and "personal" in body
        assert "not signed in" in body

    def test_shows_signed_in_once_a_credential_exists(self, browser):
        SecretStore().set("password:personal", "hunter2")
        assert "signed in</span>" in browser.get("/")[1]

    def test_download_dir_round_trips(self, browser, env):
        browser.post("/download-dir", {"download_dir": "~/Mail-dl"})
        assert str(load_config(env).download_dir).endswith("Mail-dl")


class TestSetup:
    def test_first_run_offers_to_create_the_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RUBIT_MCP_MAIL_CONFIG", str(tmp_path / "new" / "config.toml"))
        server = make_server(port=0)
        thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
        thread.start()
        try:
            client = Browser(server)
            assert client.get("/", follow=False)[2] == "/setup"
            assert "Create the config file" in client.get("/setup")[1]

            status, _, location = client.post("/setup", {}, follow=False)
            assert location == "/accounts/new"
            assert (tmp_path / "new" / "config.toml").exists()
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


class TestAccountCrud:
    NEW = {
        "name": "work",
        "provider": "generic",
        "email": "me@work.com",
        "host": "imap.work.com",
        "ssl": "",
    }

    def test_add_edit_and_remove_round_trip(self, browser, env):
        browser.post("/accounts/new", self.NEW)
        assert load_config(env).account("work").profile.host == "imap.work.com"

        browser.post("/accounts/work", dict(self.NEW, port="1993", ssl="false"))
        profile = load_config(env).account("work").profile
        assert (profile.port, profile.ssl) == (1993, False)

        browser.post("/accounts/work/delete", {})
        assert "work" not in load_config(env).accounts

    def test_saving_one_account_leaves_the_rest_of_the_file_alone(self, browser, env):
        browser.post("/accounts/new", self.NEW)
        text = env.read_text()
        assert "# a hand-written comment that must survive" in text
        assert load_config(env).account("outlook").client_id == "abc"
        assert load_config(env).account("personal").profile.host == "imap.fastmail.com"

    def test_edit_form_is_prefilled_and_the_name_is_read_only(self, browser):
        body = browser.get("/accounts/personal")[1]
        assert 'value="imap.fastmail.com"' in body
        assert "disabled" in body and "Renaming would orphan" in body

    def test_edit_saves_permissions_alongside_the_fields(self, browser, env):
        form = {
            "provider": "generic",
            "email": "you@fastmail.com",
            "host": "imap.fastmail.com",
            "ssl": "",
        }
        form.update(
            {f"enabled__personal__{tool}": "on" for tool in TOOLS if tool != "read_message"}
        )
        browser.post("/accounts/personal", form)
        assert load_config(env).account("personal").disabled_tools == ["read_message"]

    def test_edit_leaves_write_permissions_alone(self, browser, env):
        browser.post(
            "/permissions",
            {"write_allow__personal": "on", "write_tool__personal__mark_read": "on"},
            follow=False,
        )
        browser.post(
            "/accounts/personal",
            {
                "provider": "generic",
                "email": "you@fastmail.com",
                "host": "imap.fastmail.com",
                "ssl": "",
            },
        )
        account = load_config(env).account("personal")
        assert account.allow_write is True
        assert account.enabled_write_tools == ["mark_read"]

    def test_rejected_form_shows_the_error_and_writes_nothing(self, browser, env):
        original = env.read_text()
        status, body, _ = browser.post(
            "/accounts/new", {"name": "bad", "provider": "generic", "email": "me@work.com"}
        )
        assert status == 200
        assert "needs an explicit `host`" in body
        assert env.read_text() == original

    def test_duplicate_account_name_is_refused(self, browser, env):
        original = env.read_text()
        _, body, _ = browser.post("/accounts/new", dict(self.NEW, name="personal"))
        assert "already exists" in body
        assert env.read_text() == original

    def test_malformed_email_is_refused(self, browser):
        _, body, _ = browser.post("/accounts/new", dict(self.NEW, email="nope"))
        assert "does not look like an email address" in body

    def test_delete_also_drops_the_stored_credential_when_asked(self, browser, env):
        store = SecretStore()
        store.set("password:personal", "hunter2")
        assert "stored credential" in browser.get("/accounts/personal/delete")[1]

        browser.post("/accounts/personal/delete", {"drop_secret": "on"})
        assert "personal" not in load_config(env).accounts
        assert store.get("password:personal") is None

    def test_delete_can_keep_the_credential(self, browser):
        store = SecretStore()
        store.set("password:personal", "hunter2")
        browser.post("/accounts/personal/delete", {})
        assert store.get("password:personal") == "hunter2"


class TestBrokenConfig:
    """A config that fails validation is the case a user most needs help with,
    so the GUI has to open it rather than refuse it."""

    BROKEN = """# broken on purpose: a generic account with no host
[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"

[accounts.other]
provider = "generic"
email    = "two@fastmail.com"
host     = "imap.two.com"
"""

    @pytest.fixture
    def broken(self, env, browser):
        env.write_text(self.BROKEN)
        return env, browser

    def test_overview_shows_the_error_and_still_lists_the_accounts(self, broken):
        _, browser = broken
        body = browser.get("/")[1]
        assert "needs an explicit `host`" in body
        assert "personal" in body and "other" in body

    def test_the_offending_account_can_be_repaired_in_the_form(self, broken):
        env, browser = broken
        assert 'value="you@fastmail.com"' in browser.get("/accounts/personal")[1]

        browser.post(
            "/accounts/personal",
            {"provider": "generic", "email": "you@fastmail.com", "host": "imap.fastmail.com"},
        )
        config = load_config(env)
        assert set(config.accounts) == {"personal", "other"}
        assert config.account("personal").profile.host == "imap.fastmail.com"
        assert "# broken on purpose" in env.read_text()


class TestPermissionsPage:
    def test_lists_accounts_and_tools(self, browser):
        status, body, _ = browser.get("/permissions")
        assert status == 200
        assert "outlook" in body and "personal" in body
        assert "Read a message" in body

    def test_toggle_persists_and_shows_in_the_next_get(self, browser, env):
        fields = {
            f"enabled__{account}__{tool}": "on"
            for account in ("outlook", "personal")
            for tool in TOOLS
            if not (account == "outlook" and tool == "read_message")
        }
        status, _, location = browser.post("/permissions", fields, follow=False)
        assert status == 303 and location == "/permissions?saved=1"
        assert load_config(env).account("outlook").disabled_tools == ["read_message"]

        page = browser.get("/permissions")[1]
        assert 'name="enabled__outlook__read_message"' in page
        assert 'name="enabled__outlook__read_message" checked' not in page

    def test_write_tools_are_listed_and_unchecked_by_default(self, browser):
        body = browser.get("/permissions")[1]
        assert "Mark messages as read" in body
        assert "Move messages to another folder" in body
        assert 'name="write_tool__outlook__delete' not in body  # no delete/trash tool exists
        assert 'name="write_allow__outlook" checked' not in body
        assert 'name="write_tool__outlook__mark_read" checked' not in body

    def test_enabling_write_access_persists_and_shows_in_the_next_get(self, browser, env):
        fields = {f"enabled__outlook__{tool}": "on" for tool in TOOLS}
        fields["write_allow__outlook"] = "on"
        fields["write_tool__outlook__mark_read"] = "on"
        status, _, location = browser.post("/permissions", fields, follow=False)
        assert status == 303 and location == "/permissions?saved=1"

        account = load_config(env).account("outlook")
        assert account.allow_write is True
        assert account.enabled_write_tools == ["mark_read"]
        assert account.can_write("mark_read") and not account.can_write("move_message")
        assert "[accounts.personal]" in env.read_text()  # untouched account still present

        page = browser.get("/permissions")[1]
        assert 'name="write_allow__outlook" checked' in page
        assert 'name="write_tool__outlook__mark_read" checked' in page
        assert 'name="write_tool__outlook__move_message" checked' not in page

    def test_unchecking_write_access_removes_the_keys(self, browser, env):
        browser.post(
            "/permissions",
            {"write_allow__outlook": "on", "write_tool__outlook__mark_read": "on"},
            follow=False,
        )
        browser.post("/permissions", {}, follow=False)
        text = env.read_text()
        assert "allow_write" not in text
        assert "enabled_write_tools" not in text


class TestProvidersPage:
    def test_override_round_trip(self, browser, env):
        browser.post(
            "/providers",
            {
                "outlook__host": "outlook.example.com",
                "outlook__port": "1993",
                "outlook__ssl": "true",
                "outlook__authority": "https://login.example.com/common",
                "outlook__scopes": "a.scope\nb.scope",
            },
        )
        profile = load_config(env).account("outlook").profile
        assert (profile.host, profile.port) == ("outlook.example.com", 1993)
        assert profile.oauth is not None
        assert profile.oauth.scopes == ["a.scope", "b.scope"]

    def test_clearing_every_field_removes_the_table(self, browser, env):
        browser.post("/providers", {"outlook__host": "outlook.example.com"})
        browser.post("/providers", {})
        assert "providers" not in env.read_text()
        assert load_config(env).providers == {}

    def test_bad_value_is_reported_and_nothing_is_written(self, browser, env):
        original = env.read_text()
        _, body, _ = browser.post("/providers", {"outlook__port": "not-a-port"})
        assert "Port" in body or "port" in body
        assert env.read_text() == original


class TestSignIn:
    def test_password_sign_in_stores_the_secret(self, browser):
        assert "App password" in browser.get("/auth/personal")[1]
        browser.post("/auth/personal", {"password": "hunter2"})
        assert SecretStore().get("password:personal") == "hunter2"

    def test_empty_password_is_refused(self, browser):
        _, body, _ = browser.post("/auth/personal", {"password": "   "})
        assert "nothing stored" in body
        assert SecretStore().get("password:personal") is None

    def test_outlook_offers_the_device_code_flow(self, browser):
        body = browser.get("/auth/outlook")[1]
        assert "device code" in body and "Start sign-in" in body

    def test_expired_device_flow_sends_the_user_back(self, browser):
        status, body, _ = browser.get("/auth/outlook?flow=gone")
        assert status == 200
        assert "Accounts" in body


class TestDoctorPage:
    def test_renders_per_account_findings(self, browser):
        status, body, _ = browser.get("/doctor")
        assert status == 200
        assert "not signed in" in body and "account(s) not working" in body

    def test_unknown_path_is_handled(self, browser):
        assert "No such page" in browser.get("/nope")[1]
