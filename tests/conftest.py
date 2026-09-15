import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rubit_mcp_mail import shortcuts  # noqa: E402 - needs the sys.path line above


@pytest.fixture(autouse=True)
def _isolate_shortcuts(tmp_path, monkeypatch):
    """Keep desktop entries and icons out of the real home directory.

    `shortcuts` is the only thing that reads XDG_DATA_HOME, and `apply_setup`
    calls into it for real. Without this, running the suite installs a menu
    entry on the developer's machine - which it did, once.

    The Windows half needs stopping too, and for the same reason: it shells
    out to PowerShell, so on a Windows runner the suite would write real Start
    Menu and Desktop shortcuts. XDG_DATA_HOME cannot redirect those.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setattr(
        shortcuts, "_create_windows", lambda *_args, **_kwargs: ["Shortcuts: stubbed in tests."]
    )
    monkeypatch.setattr(shortcuts, "_remove_windows", lambda *_args, **_kwargs: [])
