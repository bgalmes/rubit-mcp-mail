import pytest

from rubit_mcp_mail import __version__
from rubit_mcp_mail.__main__ import main


class TestVersionFlag:
    def test_prints_the_version_and_exits_cleanly(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["rubit-mcp-mail", "--version"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_works_before_a_subcommand_would_be_required(self, monkeypatch, capsys):
        # No subcommand given - --version must not fall through to `serve`.
        monkeypatch.setattr("sys.argv", ["rubit-mcp-mail", "--version"])

        with pytest.raises(SystemExit):
            main()

        assert capsys.readouterr().out.strip()
