import http.client
import threading
from urllib.parse import urlencode

import pytest

from rubit_mcp_mail.webui import make_server

CONFIG = '''
[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "abc"

[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
'''


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    monkeypatch.setenv("RUBIT_MCP_MAIL_CONFIG", str(path))

    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, path
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_get_lists_accounts_and_tools(running_server):
    server, _path = running_server
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
    conn.request("GET", "/")
    resp = conn.getresponse()
    body = resp.read().decode()
    assert resp.status == 200
    assert "outlook" in body and "personal" in body
    assert "Read a message" in body


def test_post_toggle_persists_and_shows_in_next_get(running_server):
    server, path = running_server
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)

    # Post with every checkbox checked except outlook's read_message tool.
    fields = []
    for account in ("outlook", "personal"):
        for tool in ("list_folders", "list_messages", "search_messages", "read_message", "get_attachment"):
            if account == "outlook" and tool == "read_message":
                continue
            fields.append((f"enabled__{account}__{tool}", "on"))
    body = urlencode(fields)

    conn.request("POST", "/", body=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 303

    assert "disabled_tools" in path.read_text()

    conn.request("GET", "/")
    resp = conn.getresponse()
    page = resp.read().decode()
    assert resp.status == 200
    assert 'name="enabled__outlook__read_message"' in page
    assert 'name="enabled__outlook__read_message" checked' not in page
