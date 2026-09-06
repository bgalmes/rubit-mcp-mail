"""Local web GUI for allowing/forbidding MCP tools per account.

Binds to 127.0.0.1 only - single local user, no auth, same trust model as
`python -m http.server`. Pure stdlib (no new web-framework dependency): the
whole UI is a table of checkboxes and a Save button.
"""

from __future__ import annotations

import html
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .config import Config, config_path, load_config
from .permissions import TOOL_LABELS, TOOL_NAMES
from .permissions_editor import checkbox_name, apply_toggles, write_disabled_tools

PAGE_STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }
h1 { font-size: 1.3rem; }
table { border-collapse: collapse; margin-top: 1rem; }
th, td { padding: 0.4rem 0.8rem; border-bottom: 1px solid #ddd; text-align: left; }
th { font-weight: 600; }
td.account { font-weight: 600; }
.hint { color: #666; font-size: 0.9rem; }
button { margin-top: 1.2rem; padding: 0.5rem 1.2rem; font-size: 1rem; cursor: pointer; }
.saved { color: #146c2e; margin-bottom: 1rem; }
"""


def render_page(config: Config, saved: bool = False) -> str:
    rows = []
    for name, account in sorted(config.accounts.items()):
        cells = [f'<td class="account">{html.escape(name)}<br><span class="hint">{html.escape(account.email)}</span></td>']
        for tool in TOOL_NAMES:
            checked = "" if tool in account.disabled_tools else " checked"
            cells.append(
                f'<td><label><input type="checkbox" name="{html.escape(checkbox_name(name, tool))}"'
                f"{checked}> {html.escape(TOOL_LABELS[tool])}</label></td>"
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")

    header_cells = "".join(f"<th>{html.escape(TOOL_LABELS[tool])}</th>" for tool in TOOL_NAMES)
    saved_banner = '<p class="saved">Saved.</p>' if saved else ""
    body = "\n".join(rows) if rows else '<tr><td colspan="6">No accounts configured.</td></tr>'

    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>rubit-mcp-mail permissions</title><style>{PAGE_STYLE}</style></head>
<body>
<h1>rubit-mcp-mail - account permissions</h1>
<p class="hint">Uncheck a box to forbid that tool for an account. Changes are written to
{html.escape(str(config_path()))}. Restart the MCP server for changes to take effect.</p>
{saved_banner}
<form method="post" action="/">
<table>
<tr><th>Account</th>{header_cells}</tr>
{body}
</table>
<button type="submit">Save</button>
</form>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # keep stdout clean; this isn't a diagnostic tool

    def do_GET(self) -> None:  # noqa: N802
        query = parse_qs(urlsplit(self.path).query)
        config = load_config()
        self._respond(render_page(config, saved=query.get("saved") == ["1"]))

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        posted = parse_qs(body)

        config = load_config()
        updates = apply_toggles(list(config.accounts), posted)
        write_disabled_tools(config_path(), updates)

        self.send_response(303)
        self.send_header("Location", "/?saved=1")
        self.end_headers()

    def _respond(self, page: str) -> None:
        encoded = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def make_server(port: int = 0) -> ThreadingHTTPServer:
    """Build the (not yet running) server, bound to 127.0.0.1:`port`.

    Split out from `serve()` so tests can bind to an ephemeral port, read
    `server.server_port`, and drive `serve_forever()`/`shutdown()` themselves.
    """
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int = 0, open_browser: bool = True) -> None:
    server = make_server(port)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Listening on {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
