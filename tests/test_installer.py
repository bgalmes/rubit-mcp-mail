import os
from pathlib import Path

import pytest

from rubit_mcp_mail import installer
from rubit_mcp_mail.config import load_config
from rubit_mcp_mail.providers import THUNDERBIRD_CLIENT_ID
from rubit_mcp_mail.secrets import SecretStore

SERVER = Path("/opt/rubit-mcp-mail/rubit-mcp-mail")


class FakeStrategy:
    """Stands in for the real auth strategies, which would hit the network."""

    def __init__(self, message="Signed in as you@example.com.", error=None):
        self.message = message
        self.error = error
        self.ui = "not called"

    def interactive_setup(self, ui=None):
        self.ui = ui
        if self.error:
            raise RuntimeError(self.error)
        return self.message


class RecordingUI:
    """An AuthUI the wizard can hand to a sign-in flow."""

    def device_code(self, flow):
        self.flow = flow

    def ask_password(self, account):
        return "s3cret"


class Script:
    """A scripted stand-in for input(), which fails on an unexpected prompt."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError(f"wizard asked something unexpected: {prompt!r}")
        return self.answers.pop(0)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RUBIT_MCP_MAIL_NO_KEYRING", "1")
    return SecretStore(path=tmp_path / "secrets.json")


@pytest.fixture
def strategy(monkeypatch):
    fake = FakeStrategy()
    monkeypatch.setattr(installer, "build_auth", lambda account, store: fake)
    return fake


@pytest.fixture
def no_clients(monkeypatch):
    """Neither Claude client installed - the common case on a build machine."""
    monkeypatch.setattr(installer.claude_registration, "claude_code_available", lambda: False)
    monkeypatch.setattr(installer.claude_registration, "claude_desktop_detected", lambda: False)


@pytest.fixture
def installed_server(monkeypatch):
    monkeypatch.setattr(installer, "ensure_server_installed", lambda install_dir=None: SERVER)


class TestInstallServerBinary:
    def _source(self, tmp_path):
        source = tmp_path / "download" / installer.SERVER_BINARY_NAME
        source.parent.mkdir()
        source.write_bytes(b"#!/bin/sh\necho hi\n")
        return source

    def test_copies_into_the_target_directory(self, tmp_path):
        target = installer.install_server_binary(self._source(tmp_path), tmp_path / "bin")
        assert target == tmp_path / "bin" / installer.SERVER_BINARY_NAME
        assert target.read_bytes() == b"#!/bin/sh\necho hi\n"

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
    def test_is_executable_afterwards(self, tmp_path):
        target = installer.install_server_binary(self._source(tmp_path), tmp_path / "bin")
        assert target.stat().st_mode & 0o111

    def test_rerunning_overwrites_the_old_copy(self, tmp_path):
        source = self._source(tmp_path)
        installer.install_server_binary(source, tmp_path / "bin")
        source.write_bytes(b"newer")
        target = installer.install_server_binary(source, tmp_path / "bin")
        assert target.read_bytes() == b"newer"

    def test_installing_over_itself_is_a_noop(self, tmp_path):
        source = self._source(tmp_path)
        target = installer.install_server_binary(source, source.parent)
        assert target.read_bytes() == b"#!/bin/sh\necho hi\n"


class TestEnsureServerInstalled:
    def test_unpacks_the_bundled_binary_when_frozen(self, tmp_path, monkeypatch):
        bundled = tmp_path / "meipass" / installer.SERVER_BINARY_NAME
        bundled.parent.mkdir()
        bundled.write_bytes(b"server")
        monkeypatch.setattr(installer, "bundled_server_binary", lambda: bundled)
        assert installer.ensure_server_installed(tmp_path / "bin").read_bytes() == b"server"

    def test_falls_back_to_the_console_script_in_a_source_install(self, monkeypatch):
        monkeypatch.setattr(installer, "bundled_server_binary", lambda: None)
        monkeypatch.setattr(installer.shutil, "which", lambda name: "/usr/local/bin/rubit-mcp-mail")
        assert installer.ensure_server_installed() == Path("/usr/local/bin/rubit-mcp-mail")

    def test_says_so_when_there_is_nothing_to_register(self, monkeypatch):
        monkeypatch.setattr(installer, "bundled_server_binary", lambda: None)
        monkeypatch.setattr(installer.shutil, "which", lambda name: None)
        monkeypatch.setattr(installer.Path, "exists", lambda self: False)
        with pytest.raises(FileNotFoundError, match="Could not find"):
            installer.ensure_server_installed()


class TestSuggestAccountName:
    def test_uses_the_local_part(self):
        assert installer.suggest_account_name("Jane.Doe@outlook.com") == "janedoe"

    def test_avoids_names_already_taken(self):
        assert installer.suggest_account_name("me@a.com", {"me"}) == "me2"
        assert installer.suggest_account_name("me@a.com", {"me", "me2"}) == "me3"

    def test_falls_back_when_nothing_usable_is_left(self):
        assert installer.suggest_account_name("!!!@a.com") == "mail"


class TestValidatePlan:
    def _plan(self, **kw):
        base = {"name": "me", "provider": "outlook", "email": "me@outlook.com", "client_id": "abc"}
        return installer.SetupPlan(**{**base, **kw})

    def _problem(self, **kw) -> str:
        problem = installer.validate_plan(self._plan(**kw))
        assert problem is not None, "expected this plan to be rejected"
        return problem

    def test_a_complete_plan_passes(self):
        assert installer.validate_plan(self._plan()) is None

    def test_missing_email(self):
        assert "email address" in self._problem(email="")

    def test_malformed_email(self):
        assert "does not look like" in self._problem(email="nope")

    def test_missing_name(self):
        assert "short name" in self._problem(name=" ")

    def test_generic_needs_a_host(self):
        assert "IMAP server" in self._problem(provider="generic", client_id=None, host="")

    def test_outlook_needs_a_client_id(self):
        assert "client ID" in self._problem(client_id="")


class TestExistingAccounts:
    def test_no_config_yet(self, tmp_path):
        assert installer.existing_accounts(tmp_path / "config.toml") == {}

    def test_reads_configured_accounts(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('[accounts.a]\nprovider = "generic"\nemail = "a@b.c"\nhost = "h"\n')
        assert list(installer.existing_accounts(path)) == ["a"]

    def test_a_config_too_broken_to_load_is_not_fatal(self, tmp_path):
        # Re-running setup is how a user repairs this, so it must not dead-end.
        path = tmp_path / "config.toml"
        path.write_text('[accounts.a]\nprovider = "generic"\nemail = "a@b.c"\n')
        assert installer.existing_accounts(path) == {}


class TestApplySetup:
    def _plan(self):
        return installer.SetupPlan(
            name="outlook", provider="outlook", email="me@outlook.com", client_id="abc"
        )

    def test_writes_config_signs_in_and_registers(self, tmp_path, store, strategy, monkeypatch):
        registered = []
        monkeypatch.setattr(installer, "ensure_server_installed", lambda install_dir=None: SERVER)
        monkeypatch.setattr(installer.claude_registration, "claude_code_available", lambda: True)
        monkeypatch.setattr(installer.claude_registration, "claude_desktop_detected", lambda: False)
        monkeypatch.setattr(
            installer.claude_registration,
            "register_claude_code",
            lambda path, **kw: (registered.append(path), (True, "ok"))[1],
        )

        result = installer.apply_setup(
            self._plan(), config_file=tmp_path / "config.toml", store=store
        )

        assert load_config(tmp_path / "config.toml").account("outlook").email == "me@outlook.com"
        assert result.signin_message == strategy.message
        assert result.signin_error is None
        assert registered == [SERVER]
        assert result.ok

    def test_the_ui_is_handed_to_the_real_sign_in_flow(self, tmp_path, store, strategy, no_clients):
        ui = RecordingUI()
        installer.apply_setup(
            self._plan(), config_file=tmp_path / "config.toml", store=store, ui=ui
        )
        assert strategy.ui is ui

    def test_a_failed_sign_in_still_configures_and_registers(
        self, tmp_path, store, monkeypatch, installed_server
    ):
        monkeypatch.setattr(installer, "build_auth", lambda a, s: FakeStrategy(error="no network"))
        monkeypatch.setattr(installer.claude_registration, "claude_code_available", lambda: False)
        monkeypatch.setattr(installer.claude_registration, "claude_desktop_detected", lambda: False)

        result = installer.apply_setup(
            self._plan(), config_file=tmp_path / "config.toml", store=store
        )

        assert result.signin_error == "no network"
        assert not result.ok
        assert load_config(tmp_path / "config.toml").accounts  # config still written

    def test_a_rejected_account_raises_before_anything_else_runs(self, tmp_path, store, strategy):
        plan = installer.SetupPlan(name="x", provider="generic", email="me@a.com")
        with pytest.raises(ValueError, match="needs an explicit `host`"):
            installer.apply_setup(plan, config_file=tmp_path / "config.toml", store=store)
        assert strategy.ui == "not called"

    def test_a_second_run_keeps_the_first_account(
        self, tmp_path, store, strategy, no_clients, installed_server
    ):
        path = tmp_path / "config.toml"
        installer.apply_setup(self._plan(), config_file=path, store=store)
        second = installer.SetupPlan(
            name="personal", provider="generic", email="me@fastmail.com", host="imap.fastmail.com"
        )
        installer.apply_setup(second, config_file=path, store=store)
        assert sorted(load_config(path).accounts) == ["outlook", "personal"]

    def test_missing_clients_are_reported_rather_than_failing(
        self, tmp_path, store, strategy, no_clients, installed_server
    ):
        result = installer.apply_setup(
            self._plan(), config_file=tmp_path / "config.toml", store=store
        )
        assert any("Neither Claude Desktop nor Claude Code" in note for note in result.notes)


class TestRegisterClients:
    def test_a_client_that_blows_up_does_not_stop_the_other(self, store, monkeypatch, tmp_path):
        monkeypatch.setattr(installer.claude_registration, "claude_code_available", lambda: True)
        monkeypatch.setattr(installer.claude_registration, "claude_desktop_detected", lambda: True)
        monkeypatch.setattr(
            installer.claude_registration,
            "register_claude_code",
            lambda path, **kw: (_ for _ in ()).throw(OSError("claude exploded")),
        )
        monkeypatch.setattr(
            installer.claude_registration,
            "register_claude_desktop",
            lambda path, **kw: tmp_path / "claude_desktop_config.json",
        )

        notes = installer.register_clients(SERVER, store)

        assert any("claude exploded" in note for note in notes)
        assert any("Claude Desktop: registered" in note for note in notes)


class TestConsoleWizard:
    def test_sets_up_a_new_outlook_account(
        self, tmp_path, store, strategy, no_clients, installed_server
    ):
        path = tmp_path / "config.toml"
        script = Script("", "me@outlook.com", "", "")  # provider, email, name, client id
        lines = []

        code = installer.console_wizard(
            input_fn=script, config_file=path, store=store, out=lines.append
        )

        account = load_config(path).account("me")
        assert (code, account.provider, account.client_id) == (0, "outlook", THUNDERBIRD_CLIENT_ID)
        assert any("Signed in" in line for line in lines)

    def test_sets_up_a_generic_account(
        self, tmp_path, store, strategy, no_clients, installed_server
    ):
        path = tmp_path / "config.toml"
        script = Script("other", "me@fastmail.com", "personal", "imap.fastmail.com")

        installer.console_wizard(input_fn=script, config_file=path, store=store, out=lambda _: None)

        account = load_config(path).account("personal")
        assert (account.provider, account.profile.host) == ("generic", "imap.fastmail.com")

    def test_repairing_reuses_the_existing_account(
        self, tmp_path, store, strategy, no_clients, installed_server
    ):
        path = tmp_path / "config.toml"
        path.write_text(
            'download_dir = "~/d"\n\n[accounts.work]\n'
            'provider = "generic"\nemail = "me@corp.com"\nhost = "imap.corp.com"\n'
        )
        script = Script("repair", "work")

        code = installer.console_wizard(
            input_fn=script, config_file=path, store=store, out=lambda _: None
        )

        assert code == 0
        account = load_config(path).account("work")
        assert (account.email, account.profile.host) == ("me@corp.com", "imap.corp.com")

    def test_a_failed_sign_in_exits_nonzero(self, tmp_path, store, monkeypatch, no_clients):
        monkeypatch.setattr(installer, "build_auth", lambda a, s: FakeStrategy(error="nope"))
        monkeypatch.setattr(installer, "ensure_server_installed", lambda install_dir=None: SERVER)
        script = Script("", "me@outlook.com", "", "")
        lines = []

        code = installer.console_wizard(
            input_fn=script, config_file=tmp_path / "config.toml", store=store, out=lines.append
        )

        assert code == 1
        assert any("nope" in line for line in lines)
