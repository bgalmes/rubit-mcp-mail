"""HTML for the local config GUI.

Rendering only - every function here takes plain data and returns a string, so
the pages can be exercised in tests without an HTTP server. Routing, form
parsing and file writes live in webui.py.

Everything that came from the config file, a form, or a server error is passed
through `html.escape`; the pages are assembled by hand rather than with a
template engine to keep the project dependency-free.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .config import Config
from .config_editor import checkbox_name
from .diagnostics import AccountReport, Report
from .permissions import TOOL_LABELS, TOOL_NAMES
from .providers import PROFILES, THUNDERBIRD_CLIENT_ID

PAGE_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; margin: 0; color: #1a1a1a; background: #fbfbfa; }
main { max-width: 60rem; margin: 0 auto; padding: 1.5rem 2rem 4rem; }
nav { background: #24292f; padding: 0.7rem 2rem; }
nav a { color: #e8e8e8; text-decoration: none; margin-right: 1.4rem; font-size: 0.95rem; }
nav a:hover, nav a.on { color: #fff; text-decoration: underline; }
h1 { font-size: 1.35rem; margin-bottom: 0.3rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; }
table { border-collapse: collapse; margin-top: 1rem; width: 100%; }
th, td { padding: 0.45rem 0.8rem; border-bottom: 1px solid #ddd; text-align: left;
         vertical-align: top; }
th { font-weight: 600; font-size: 0.85rem; text-transform: uppercase; color: #555; }
td.account { font-weight: 600; }
.hint { color: #666; font-size: 0.9rem; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem; }
button, .button { margin-top: 0.4rem; padding: 0.45rem 1.1rem; font-size: 0.95rem;
         cursor: pointer; border: 1px solid #b6b6b6; border-radius: 5px; background: #fff;
         color: #1a1a1a; text-decoration: none; display: inline-block; }
button.primary { background: #0b5cd5; border-color: #0b5cd5; color: #fff; }
button.danger { background: #b32b1f; border-color: #b32b1f; color: #fff; }
.banner { padding: 0.6rem 0.9rem; border-radius: 5px; margin: 1rem 0; }
.saved { background: #e2f4e6; color: #14532d; }
.error { background: #fbe3e0; color: #7a1c12; }
.warn { background: #fdf3d8; color: #6b4d06; }
label.field { display: block; margin: 0.9rem 0; }
label.field span { display: block; font-weight: 600; margin-bottom: 0.2rem; }
label.field span.hint { font-weight: 400; margin: 0.15rem 0 0; }
p button { margin-top: 0; padding: 0.15rem 0.55rem; font-size: 0.85rem; }
input[type=text], input[type=password], select, textarea {
  width: 100%; max-width: 34rem; padding: 0.4rem; font-size: 0.95rem;
  border: 1px solid #b6b6b6; border-radius: 4px; background: #fff; color: #1a1a1a; }
fieldset { border: 1px solid #ddd; border-radius: 6px; margin: 1.2rem 0;
           padding: 0.4rem 1rem 1rem; }
legend { font-weight: 600; padding: 0 0.4rem; }
.badge { font-size: 0.8rem; padding: 0.15rem 0.5rem; border-radius: 999px; }
.badge.ok { background: #e2f4e6; color: #14532d; }
.badge.needs_auth { background: #fdf3d8; color: #6b4d06; }
.badge.error { background: #fbe3e0; color: #7a1c12; }
pre { background: #f1f1ef; padding: 0.8rem; border-radius: 5px; overflow-x: auto;
      font-size: 0.85rem; }
pre.wrap { white-space: pre-wrap; }
.actions { white-space: nowrap; }
.actions a { margin-right: 0.7rem; }
"""

NAV = (
    ("/", "Accounts"),
    ("/permissions", "Permissions"),
    ("/providers", "Providers"),
    ("/doctor", "Doctor"),
)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _nav_link(href: str, label: str, active: str) -> str:
    on = ' class="on"' if href == active else ""
    return f'<a href="{esc(href)}"{on}>{esc(label)}</a>'


def layout(title: str, body: str, *, active: str = "", banner: str = "", error: str = "") -> str:
    links = "".join(_nav_link(href, label, active) for href, label in NAV)
    banners = ""
    if error:
        banners += f'<p class="banner error">{esc(error)}</p>'
    if banner:
        banners += f'<p class="banner saved">{esc(banner)}</p>'
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{esc(title)}</title><style>{PAGE_STYLE}</style></head>
<body>
<nav>{links}</nav>
<main>
{banners}
{body}
</main>
</body>
</html>
"""


def _text_field(label: str, name: str, value: Any, *, hint: str = "", kind: str = "text") -> str:
    hint_html = f'<span class="hint">{esc(hint)}</span>' if hint else ""
    return (
        f'<label class="field"><span>{esc(label)}</span>'
        f'<input type="{esc(kind)}" name="{esc(name)}" value="{esc(value)}">'
        f"{hint_html}</label>"
    )


def _select(
    label: str, name: str, value: Any, choices: list[tuple[str, str]], *, hint: str = ""
) -> str:
    current = "" if value is None else str(value).lower()
    options = "".join(
        f'<option value="{esc(key)}"{" selected" if key == current else ""}>{esc(text)}</option>'
        for key, text in choices
    )
    hint_html = f'<span class="hint">{esc(hint)}</span>' if hint else ""
    return (
        f'<label class="field"><span>{esc(label)}</span>'
        f'<select name="{esc(name)}">{options}</select>{hint_html}</label>'
    )


def _checkbox(label: str, name: str, checked: bool, *, hint: str = "") -> str:
    hint_html = f' <span class="hint">{esc(hint)}</span>' if hint else ""
    mark = " checked" if checked else ""
    return (
        f'<label class="field"><span><input type="checkbox" name="{esc(name)}"{mark}> '
        f"{esc(label)}</span>{hint_html}</label>"
    )


# -- first run ---------------------------------------------------------------
def render_setup(path: Path) -> str:
    body = f"""
<h1>Welcome to rubit-mcp-mail</h1>
<p>There is no config file yet. This page writes a starter one at
<span class="mono">{esc(path)}</span>; you can then add your mail accounts here,
without ever opening a text editor.</p>
<form method="post" action="/setup">
<button class="primary" type="submit">Create the config file</button>
</form>
"""
    return layout("rubit-mcp-mail setup", body)


# -- accounts overview -------------------------------------------------------
def _auth_badge(report: AccountReport) -> str:
    if report.error and not report.auth_state:
        return '<span class="badge error">config error</span>'
    state = report.auth_state or "error"
    label = {"ok": "signed in", "needs_auth": "not signed in"}.get(state, state)
    return f'<span class="badge {esc(state)}">{esc(label)}</span>'


def render_overview(report: Report, raw_accounts: dict[str, dict], *, banner: str = "") -> str:
    rows = []
    for account in report.accounts:
        detail = account.auth_detail or account.error or ""
        summary = detail.split(". ")[0]
        if len(summary) > 90:
            summary = summary[:90].rsplit(" ", 1)[0] + "..."
        elif summary != detail:
            summary += "..."
        rows.append(f"""<tr>
<td class="account">{esc(account.name)}<br><span class="hint">{esc(account.email)}</span></td>
<td>{esc(account.provider)}<br>
<span class="hint mono">{esc(account.host)}:{esc(account.port)}</span></td>
<td>{_auth_badge(account)}<br>
<span class="hint" title="{esc(detail)}">{esc(summary)}</span></td>
<td class="actions">
  <a href="/accounts/{esc(account.name)}">Edit</a>
  <a href="/auth/{esc(account.name)}">Sign in</a>
  <a href="/accounts/{esc(account.name)}/delete">Remove</a>
</td></tr>""")

    if report.config_error:
        # The file exists but does not load. Every account is still listed from
        # the raw TOML so the offending one can be opened and repaired here.
        for name in sorted(raw_accounts):
            rows.append(f"""<tr>
<td class="account">{esc(name)}<br>
<span class="hint">{esc(raw_accounts[name].get("email", ""))}</span></td>
<td>{esc(raw_accounts[name].get("provider", "generic"))}</td>
<td><span class="badge error">not loaded</span></td>
<td class="actions"><a href="/accounts/{esc(name)}">Edit</a>
  <a href="/accounts/{esc(name)}/delete">Remove</a></td></tr>""")

    table = (
        "\n".join(rows) or '<tr><td colspan="4" class="hint">No accounts configured yet.</td></tr>'
    )
    secrets_note = ""
    if report.secrets_warning:
        secrets_note = (
            '<p class="banner warn">Credentials in the OS keyring are not readable from this '
            "process, so anything signed in elsewhere will look signed out here.</p>"
        )
    overrides = ""
    if report.provider_overrides:
        listed = "; ".join(
            f"{esc(name)} ({esc(', '.join(keys))})"
            for name, keys in report.provider_overrides.items()
        )
        overrides = f'<p class="hint">Provider overrides in effect: {listed}</p>'

    body = f"""
<h1>Accounts</h1>
<p class="hint">Config: <span class="mono">{esc(report.config_path)}</span><br>
Secrets: <span class="mono">{esc(report.secrets_backend)}</span></p>
{secrets_note}
{overrides}
<table>
<tr><th>Account</th><th>Provider</th><th>Sign-in</th><th></th></tr>
{table}
</table>
<p><a class="button" href="/accounts/new">Add an account</a></p>

<h2>Downloads</h2>
<form method="post" action="/download-dir">
{
        _text_field(
            "Attachment download directory",
            "download_dir",
            report.download_dir or "",
            hint="Where get_attachment saves files. Leave empty for the default.",
        )
    }
<button type="submit">Save</button>
</form>
<p class="hint">A running MCP server reads the config once at startup, so restart it
(or Claude Desktop) for changes here to take effect.</p>
"""
    return layout(
        "rubit-mcp-mail", body, active="/", banner=banner, error=report.config_error or ""
    )


# -- account form ------------------------------------------------------------
PROVIDER_LABELS = {"outlook": "Outlook.com / Microsoft 365", "generic": "Other IMAP server"}


def render_account_form(
    name: str,
    fields: dict[str, Any],
    *,
    is_new: bool,
    error: str = "",
    disabled_tools: list[str] | None = None,
) -> str:
    provider = str(fields.get("provider") or "generic")
    options = "".join(
        f'<option value="{esc(key)}"{" selected" if key == provider else ""}>'
        f"{esc(PROVIDER_LABELS.get(key, key))}</option>"
        for key in sorted(PROFILES)
    )
    name_input = (
        _text_field(
            "Account name",
            "name",
            name,
            hint="Short handle you will use in Claude, e.g. 'work'. Letters, digits, . - _",
        )
        if is_new
        else f'<label class="field"><span>Account name</span>'
        f'<input type="text" value="{esc(name)}" disabled>'
        f'<span class="hint">Renaming would orphan the stored credential. '
        f"To rename, add a new account and remove this one.</span></label>"
    )

    tools = ""
    if disabled_tools is not None:
        boxes = "".join(
            _checkbox(TOOL_LABELS[tool], checkbox_name(name, tool), tool not in disabled_tools)
            for tool in TOOL_NAMES
        )
        tools = f"""<fieldset><legend>Allowed tools</legend>
<p class="hint">Unchecked tools are refused for this account.</p>{boxes}</fieldset>"""

    ssl_field = _select(
        "SSL/TLS",
        "ssl",
        fields.get("ssl"),
        [("", "Provider default"), ("true", "On"), ("false", "Off (plaintext)")],
        hint="Only change this for a server that does not do implicit TLS.",
    )

    body = f"""
<h1>{"Add an account" if is_new else esc(name)}</h1>
<form method="post">
{name_input}
<label class="field"><span>Provider</span>
<select name="provider" id="provider">{options}</select></label>
{
        _text_field(
            "Email address",
            "email",
            fields.get("email"),
            hint="The mailbox address you sign in with.",
        )
    }

<fieldset data-provider="outlook"><legend>Outlook sign-in</legend>
{
        _text_field(
            "Application (client) ID",
            "client_id",
            fields.get("client_id"),
            hint="From your Azure app registration - see the README.",
        )
    }
<p class="hint">No Azure app? Use Thunderbird's public client ID
<span class="mono">{esc(THUNDERBIRD_CLIENT_ID)}</span>
(<button type="button" onclick="document.getElementsByName('client_id')[0].value='{
        esc(THUNDERBIRD_CLIENT_ID)
    }'">use it</button>).
The Microsoft consent screen will then say "Thunderbird", and Microsoft could
rotate that ID at any time.</p>
</fieldset>

<fieldset data-provider="generic"><legend>IMAP server</legend>
{_text_field("Host", "host", fields.get("host"), hint="e.g. imap.fastmail.com")}
{_text_field("Port", "port", fields.get("port"), hint="Leave empty for 993.")}
{ssl_field}
</fieldset>
{tools}
<button class="primary" type="submit">Save</button>
<a class="button" href="/">Cancel</a>
</form>
<script>
function syncProvider() {{
  var chosen = document.getElementById('provider').value;
  document.querySelectorAll('[data-provider]').forEach(function (box) {{
    box.style.display = box.dataset.provider === chosen ? '' : 'none';
  }});
}}
document.getElementById('provider').addEventListener('change', syncProvider);
syncProvider();
</script>
"""
    return layout("Account - rubit-mcp-mail", body, active="/", error=error)


def render_delete(name: str, has_secret: bool) -> str:
    secret_box = (
        _checkbox(
            "Also delete the stored credential",
            "drop_secret",
            True,
            hint="Leaves nothing behind in the keyring or secrets file.",
        )
        if has_secret
        else ""
    )
    body = f"""
<h1>Remove {esc(name)}?</h1>
<p>This deletes the <span class="mono">[accounts.{esc(name)}]</span> section from your
config file. Nothing in your mailbox is touched.</p>
<form method="post">
{secret_box}
<button class="danger" type="submit">Remove account</button>
<a class="button" href="/">Cancel</a>
</form>
"""
    return layout("Remove account", body, active="/")


# -- permissions -------------------------------------------------------------
def render_permissions(config: Config, saved: bool = False) -> str:
    rows = []
    for name, account in sorted(config.accounts.items()):
        cells = [
            f'<td class="account">{esc(name)}<br>'
            f'<span class="hint">{esc(account.email)}</span></td>'
        ]
        for tool in TOOL_NAMES:
            checked = "" if tool in account.disabled_tools else " checked"
            cells.append(
                f'<td><label><input type="checkbox" name="{esc(checkbox_name(name, tool))}"'
                f"{checked}> {esc(TOOL_LABELS[tool])}</label></td>"
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")

    header_cells = "".join(f"<th>{esc(TOOL_LABELS[tool])}</th>" for tool in TOOL_NAMES)
    body_rows = "\n".join(rows) or '<tr><td colspan="6">No accounts configured.</td></tr>'
    body = f"""
<h1>Account permissions</h1>
<p class="hint">Uncheck a box to forbid that tool for an account. Restart the MCP server
for changes to take effect.</p>
<form method="post" action="/permissions">
<table>
<tr><th>Account</th>{header_cells}</tr>
{body_rows}
</table>
<button class="primary" type="submit">Save</button>
</form>
"""
    return layout(
        "Permissions - rubit-mcp-mail",
        body,
        active="/permissions",
        banner="Saved." if saved else "",
    )


# -- provider overrides ------------------------------------------------------
def render_providers(overrides: dict[str, dict], error: str = "", banner: str = "") -> str:
    blocks = []
    for provider in sorted(PROFILES):
        profile = PROFILES[provider]
        current = overrides.get(provider, {})
        oauth = current.get("oauth", {}) if isinstance(current.get("oauth"), dict) else {}
        scopes = oauth.get("scopes") or []
        oauth_fields = ""
        if profile.oauth is not None:
            oauth_fields = f"""
{
                _text_field(
                    "OAuth authority",
                    f"{provider}__authority",
                    oauth.get("authority", ""),
                    hint=f"Built in: {profile.oauth.authority}",
                )
            }
<label class="field"><span>OAuth scopes (one per line)</span>
<textarea name="{esc(provider)}__scopes" rows="3">{esc(chr(10).join(scopes))}</textarea>
<span class="hint">Built in: {esc(" ".join(profile.oauth.scopes))}</span></label>"""

        host_field = _text_field(
            "IMAP host",
            f"{provider}__host",
            current.get("host", ""),
            hint=f"Built in: {profile.host or '(set per account)'}",
        )
        port_field = _text_field(
            "Port", f"{provider}__port", current.get("port", ""), hint=f"Built in: {profile.port}"
        )
        ssl_field = _select(
            "SSL",
            f"{provider}__ssl",
            current.get("ssl"),
            [("", "Provider default"), ("true", "On"), ("false", "Off (plaintext)")],
            hint=f"Built in: {str(profile.ssl).lower()}",
        )
        label = esc(PROVIDER_LABELS.get(provider, provider))
        legend = f'{label} (<span class="mono">{esc(provider)}</span>)'
        blocks.append(f"""<fieldset><legend>{legend}</legend>
{host_field}
{port_field}
{ssl_field}
{oauth_fields}
</fieldset>""")

    body = f"""
<h1>Provider overrides</h1>
<p class="hint">The IMAP hosts and OAuth endpoints are compiled into this release. If a
provider changes one, correct it here and it takes effect immediately - no new release
needed. Leave a field empty to keep the built-in value.</p>
<form method="post" action="/providers">
{"".join(blocks)}
<button class="primary" type="submit">Save</button>
</form>
"""
    return layout(
        "Providers - rubit-mcp-mail", body, active="/providers", error=error, banner=banner
    )


# -- sign in -----------------------------------------------------------------
def render_password_signin(name: str, email: str, host: str, error: str = "") -> str:
    body = f"""
<h1>Sign in: {esc(name)}</h1>
<p class="hint">{esc(email)} on <span class="mono">{esc(host)}</span></p>
<p>Enter the app password for this mailbox. It is stored through the same keyring
(or owner-only file) the CLI uses - never in the config file.</p>
<form method="post">
{_text_field("App password", "password", "", kind="password")}
<button class="primary" type="submit">Save password</button>
<a class="button" href="/">Cancel</a>
</form>
"""
    return layout("Sign in", body, active="/", error=error)


def render_device_start(name: str, email: str, error: str = "") -> str:
    body = f"""
<h1>Sign in: {esc(name)}</h1>
<p class="hint">{esc(email)}</p>
<p>Microsoft signs you in with a device code: this page shows a short code, you type it
into microsoft.com in another tab, and the token is cached here when you are done.</p>
<form method="post">
<button class="primary" type="submit">Start sign-in</button>
<a class="button" href="/">Cancel</a>
</form>
"""
    return layout("Sign in", body, active="/", error=error)


def render_device_flow(name: str, pending: dict) -> str:
    state = pending.get("state")
    if state == "done":
        body = f"""
<h1>Signed in: {esc(name)}</h1>
<p class="banner saved">{esc(pending.get("detail") or "Token cached.")}</p>
<p><a class="button" href="/">Back to accounts</a>
<a class="button" href="/doctor/{esc(name)}">Check it works</a></p>
"""
        return layout("Signed in", body, active="/")
    if state == "error":
        body = f"""
<h1>Sign-in failed: {esc(name)}</h1>
<pre>{esc(pending.get("detail") or "")}</pre>
<p><a class="button" href="/auth/{esc(name)}">Try again</a>
<a class="button" href="/">Back to accounts</a></p>
"""
        return layout("Sign-in failed", body, active="/")

    uri = pending.get("uri") or "https://microsoft.com/devicelogin"
    body = f"""
<h1>Finish signing in: {esc(name)}</h1>
<p>Open <a href="{esc(uri)}" target="_blank" rel="noopener">{esc(uri)}</a> and enter this code:</p>
<p class="mono" style="font-size:2rem">{esc(pending.get("code"))}</p>
<pre class="wrap">{esc(pending.get("message"))}</pre>
<p class="hint">Waiting for you to finish. This page checks every few seconds.</p>
"""
    # Server-side polling by refresh: no JS, and it keeps working if the tab is
    # restored later - the flow itself lives on the server until it completes.
    page = layout("Signing in", body, active="/")
    return page.replace("<head>", '<head><meta http-equiv="refresh" content="4">', 1)


# -- doctor ------------------------------------------------------------------
def _doctor_account(report: AccountReport) -> str:
    if report.error and not report.auth_state:
        return f"<h2>{esc(report.name)}</h2><p class='banner error'>{esc(report.error)}</p>"

    lines = [
        f"<h2>{esc(report.name)} {_auth_badge(report)}</h2>",
        f'<p class="hint mono">{esc(report.provider)} - {esc(report.host)}:{esc(report.port)}'
        f" ssl={esc(report.ssl)} - {esc(report.email)}</p>",
    ]
    if report.auth_state != "ok":
        lines.append(f'<p class="banner warn">{esc(report.auth_detail or "not signed in")}</p>')
        lines.append(f'<p><a class="button" href="/auth/{esc(report.name)}">Sign in</a></p>')
        return "".join(lines)
    if report.error:
        lines.append(f'<p class="banner error">{esc(report.error)}</p>')
        return "".join(lines)
    if not report.connected:
        lines.append('<p class="hint">Credential found. No connection was attempted.</p>')
        return "".join(lines)

    folders = "\n".join(
        f"[{folder.role:<7}] {folder.name:<28} "
        + (
            f"{folder.messages:>6} msgs, {folder.unseen or 0} unread"
            if folder.messages is not None
            else ""
        )
        for folder in report.folders
    )
    lines.append(f'<p class="hint">capabilities: {esc(" ".join(report.capabilities[:12]))}</p>')
    lines.append(f"<p>{len(report.folders)} folders found</p><pre>{esc(folders)}</pre>")
    return "".join(lines)


def render_doctor(report: Report, connected: bool) -> str:
    head = f"""
<h1>Doctor</h1>
<p class="hint">Config: <span class="mono">{esc(report.config_path)}</span><br>
Downloads: <span class="mono">{esc(report.download_dir)}</span><br>
Secrets: <span class="mono">{esc(report.secrets_backend)}</span></p>
"""
    if report.config_error:
        return layout(
            "Doctor",
            head + f'<p class="banner error">{esc(report.config_error)}</p>',
            active="/doctor",
        )

    note = (
        "" if connected else '<p class="hint">Credentials only - no connection was attempted.</p>'
    )
    summary = (
        f'<p class="banner error">{report.failures} account(s) not working.</p>'
        if report.failures
        else '<p class="banner saved">All accounts OK.</p>'
    )
    accounts = "".join(_doctor_account(account) for account in report.accounts) or (
        '<p class="hint">No accounts configured.</p>'
    )
    return layout("Doctor", head + note + summary + accounts, active="/doctor")
