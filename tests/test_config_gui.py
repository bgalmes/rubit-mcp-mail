"""What the settings window can be checked on without a display.

The window itself needs a real Tk, which build machines and CI containers
usually lack. Everything that decides *what* it shows - the account rows, the
provider form parsing, the doctor text - is a plain function, and that is what
is tested here.
"""

from pathlib import Path

import pytest
import tomlkit

from rubit_mcp_mail import config_gui
from rubit_mcp_mail.diagnostics import AccountReport, Report
from rubit_mcp_mail.models import Folder

CONFIG = """download_dir = "~/Downloads/rubit-mcp-mail"

[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "abc"

[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
disabled_tools = ["get_attachment"]
"""


def signed_in(name="outlook", **kwargs):
    fields = {
        "provider": "outlook",
        "email": f"{name}@example.com",
        "host": "outlook.office365.com",
        "port": 993,
        "auth_state": "ok",
        "connected": True,
    }
    fields.update(kwargs)
    return AccountReport(name=name, **fields)


class TestRawAccounts:
    def test_reads_tables_straight_from_the_toml(self):
        accounts = config_gui.raw_accounts(tomlkit.parse(CONFIG))

        assert sorted(accounts) == ["outlook", "personal"]
        assert accounts["personal"]["host"] == "imap.fastmail.com"
        assert accounts["personal"]["disabled_tools"] == ["get_attachment"]

    def test_a_file_with_no_accounts_is_empty_not_an_error(self):
        assert config_gui.raw_accounts(tomlkit.parse('download_dir = "~/x"')) == {}


class TestAuthLabel:
    def test_signed_in(self):
        assert config_gui.auth_label(signed_in()) == "signed in"

    def test_not_signed_in(self):
        assert config_gui.auth_label(signed_in(auth_state="needs_auth")) == "not signed in"

    def test_a_config_error_outranks_a_missing_state(self):
        report = AccountReport(name="x", error="no such provider")
        assert config_gui.auth_label(report) == "config error"


class TestSummarise:
    def test_keeps_a_short_diagnosis_whole(self):
        assert config_gui.summarise("no password stored") == "no password stored"

    def test_takes_the_first_sentence(self):
        assert config_gui.summarise("Token expired. Run auth again.") == "Token expired..."

    def test_clips_on_a_word_boundary(self):
        summary = config_gui.summarise("word " * 40)

        assert len(summary) <= 93
        assert summary.endswith("...")


class TestAccountRows:
    def test_one_row_per_account(self):
        report = Report(config_path=Path("/c"), accounts=[signed_in("a"), signed_in("b")])

        rows = config_gui.account_rows(report, {})

        assert [row[0] for row in rows] == ["a", "b"]
        assert rows[0][3] == "outlook.office365.com:993"
        assert rows[0][4] == "signed in"

    def test_an_unloadable_config_still_lists_every_account(self):
        # The case a user most needs the window for: nothing validates, but each
        # account must still be openable so it can be repaired.
        report = Report(config_path=Path("/c"), config_error="port must be an integer")

        rows = config_gui.account_rows(report, config_gui.raw_accounts(tomlkit.parse(CONFIG)))

        assert [row[0] for row in rows] == ["outlook", "personal"]
        assert all(row[4] == "not loaded" for row in rows)

    def test_no_accounts_is_an_empty_list(self):
        assert config_gui.account_rows(Report(config_path=Path("/c")), {}) == []


class TestParseProviderForm:
    def test_empty_form_produces_empty_fields(self):
        fields = config_gui.parse_provider_form(
            {"host": "", "port": "", "ssl": "", "authority": ""}, ""
        )

        assert fields == {"host": "", "port": "", "ssl": "", "authority": "", "scopes": []}

    def test_port_becomes_an_integer(self):
        fields = config_gui.parse_provider_form({"port": "1993"}, "")

        assert fields["port"] == 1993

    def test_a_non_numeric_port_is_refused(self):
        with pytest.raises(ValueError, match="whole number"):
            config_gui.parse_provider_form({"port": "993a"}, "")

    @pytest.mark.parametrize(("text", "expected"), [("true", True), ("false", False)])
    def test_ssl_becomes_a_boolean(self, text, expected):
        assert config_gui.parse_provider_form({"ssl": text}, "")["ssl"] is expected

    def test_an_unrecognised_ssl_value_is_refused(self):
        with pytest.raises(ValueError, match="true"):
            config_gui.parse_provider_form({"ssl": "yes"}, "")

    def test_scopes_are_split_per_line_and_stripped(self):
        fields = config_gui.parse_provider_form({}, "  one \n\n two  \n")

        assert fields["scopes"] == ["one", "two"]

    def test_surrounding_whitespace_is_trimmed(self):
        fields = config_gui.parse_provider_form({"host": "  imap.x.com  "}, "")

        assert fields["host"] == "imap.x.com"


class TestDoctorText:
    def test_reports_an_unloadable_config_and_stops(self):
        report = Report(config_path=Path("/c"), config_error="bad port")

        text = config_gui.doctor_text(report)

        assert "does not load: bad port" in text
        assert "accounts OK" not in text

    def test_says_so_when_nothing_is_configured(self):
        assert "No accounts configured." in config_gui.doctor_text(Report(config_path=Path("/c")))

    def test_includes_the_version(self):
        report = Report(config_path=Path("/c"), version="1.2.3")
        assert "Version:   1.2.3" in config_gui.doctor_text(report)

    def test_lists_folders_for_a_connected_account(self):
        account = signed_in(
            folders=[Folder(name="INBOX", role="inbox", messages=12, unseen=3)],
            capabilities=["IMAP4REV1"],
        )
        report = Report(config_path=Path("/c"), accounts=[account])

        text = config_gui.doctor_text(report)

        assert "All accounts OK." in text
        assert "1 folders found" in text
        assert "12 msgs, 3 unread" in text

    def test_counts_failures(self):
        report = Report(
            config_path=Path("/c"),
            accounts=[signed_in("a"), signed_in("b", auth_state="needs_auth", connected=False)],
        )

        text = config_gui.doctor_text(report)

        assert "1 account(s) not working." in text

    def test_a_credential_only_check_says_it_did_not_connect(self):
        report = Report(config_path=Path("/c"), accounts=[signed_in(connected=False)])

        assert "No connection was attempted." in config_gui.doctor_text(report)


class TestSslChoice:
    @pytest.mark.parametrize(
        ("stored", "label"),
        [
            (None, "Provider default"),
            ("", "Provider default"),
            (True, "On"),
            (False, "Off (plaintext)"),
        ],
    )
    def test_round_trips_through_the_dropdown(self, stored, label):
        assert config_gui._ssl_choice(stored) == label
        # Whatever label comes back must be one the form knows how to submit.
        assert label in config_gui._SSL_CHOICES


class TestRun:
    def test_reports_rather_than_crashing_when_tkinter_is_missing(self, monkeypatch, capsys):
        import builtins

        real_import = builtins.__import__

        def no_tkinter(name, *args, **kwargs):
            if name == "tkinter":
                raise ImportError("no _tkinter")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_tkinter)

        assert config_gui.run() == 1
        assert "no graphical display" in capsys.readouterr().err.lower()

    def test_every_page_name_maps_to_a_tab(self):
        # `run(page=...)` indexes the notebook with PAGES, so the CLI's page
        # names and the tab order cannot drift apart.
        assert config_gui.PAGES == ("accounts", "permissions", "providers", "doctor")
