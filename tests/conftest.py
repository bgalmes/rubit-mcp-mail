import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def _isolate_shortcuts(tmp_path, monkeypatch):
    """Keep desktop entries and icons out of the real home directory.

    `shortcuts` is the only thing that reads XDG_DATA_HOME, and `apply_setup`
    calls into it for real. Without this, running the suite installs a menu
    entry on the developer's machine - which it did, once.
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
