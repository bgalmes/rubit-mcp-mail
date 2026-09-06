# rubit-mcp-mail

A read-only MCP server for reading your mail. Provider-agnostic: it speaks IMAP,
so it works with Outlook.com, Gmail, Fastmail, iCloud, or a self-hosted server —
the provider is a line of config, not a code change.

**Read-only by construction.** Folders are opened with `EXAMINE`, never `SELECT`,
and bodies are fetched with `BODY.PEEK`, so reading a message does not even mark
it as read. There are no send, move, delete, or flag code paths, and a test
asserts none are ever added.

## Tools

| Tool | What it does |
| --- | --- |
| `list_accounts` | Configured accounts and whether each is authenticated |
| `list_folders` | Folders with normalized roles and unread counts |
| `list_messages` | Browse a folder, newest first, paginated |
| `search_messages` | Server-side search by text, sender, subject, date range, unread |
| `read_message` | Full headers, body text, attachment metadata |
| `get_attachment` | Save one attachment into the download directory |

Folders are addressed by **role** — `inbox`, `sent`, `drafts`, `junk`, `trash`,
`archive` — so you never need to know that Outlook calls it `Junk Email` while
Gmail calls it `[Gmail]/Spam`. Raw folder names work too.

Roles come from the server's SPECIAL-USE flags where available. Outlook.com does
not advertise them, so there names are matched instead — accent-insensitively,
and including the localizations Outlook ships (Spanish, Catalan, French, German,
Italian, Portuguese), so a mailbox with `Elementos enviados` still resolves to
`sent`. Run `rubit-mcp-mail doctor` to see exactly how your folders were classified;
any folder that comes out as `other` can still be addressed by its raw name.

`list_messages` and `search_messages` return opaque **handles**. Pass one to
`read_message` or `get_attachment`. A handle encodes the folder's `UIDVALIDITY`,
so if the mailbox is renumbered you get a clear "re-run the search" error rather
than the wrong message.

## Permissions

Any of the account-scoped tools (all but `list_accounts`) can be forbidden for
a given account with `disabled_tools` in `config.toml`:

```toml
[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
disabled_tools = ["get_attachment"]
```

A blocked call returns a plain `Error: ...` string to the model rather than
failing silently. This is meant for future write tools (send, mark as
read/unread, etc.) that don't exist yet, but it works against today's
read-only tools too — for example to keep attachments off a shared account.

Rather than editing TOML by hand, run:

```bash
rubit-mcp-mail permissions
```

This opens a small local web page (bound to `127.0.0.1` only — no
authentication, same trust model as `python -m http.server`) listing every
configured account with a checkbox per tool; unchecking one and saving writes
`disabled_tools` back into `config.toml`, leaving every other line, comment,
and ordering untouched. Use `--port` to pick a fixed port and `--no-browser`
to skip auto-opening one.

**A `serve` process caches its config on first read**, so toggling a
permission here does not affect a *running* MCP server (e.g. one launched by
Claude Desktop) until it is restarted.

## Install

```bash
cd /path/to/rubit-mcp-mail
conda create -p ./.venv python=3.12 pip -y     # this machine has no python3-venv
./.venv/bin/python -m pip install -e .
```

### Install on Windows

Use a standard venv (no conda needed — `venv` ships with the Python installer
on Windows) from PowerShell:

```powershell
cd C:\path\to\rubit-mcp-mail
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

Everywhere the rest of this README shows `./.venv/bin/rubit-mcp-mail`, use
`.venv\Scripts\rubit-mcp-mail.exe` instead (or `.venv\Scripts\python.exe -m
rubit_mcp_mail` if you'd rather not depend on the `.exe` shim). For example:

```powershell
.venv\Scripts\rubit-mcp-mail.exe auth outlook
.venv\Scripts\rubit-mcp-mail.exe doctor
```

The config file lives at `%USERPROFILE%\.config\rubit-mcp-mail\config.toml`
— `Path.home() / ".config"` resolves there on Windows too, so create it the
same way the [Configure](#2-configure) section shows, just with `mkdir` and a
text editor instead of the `cat` heredoc:

```powershell
mkdir $env:USERPROFILE\.config\rubit-mcp-mail
notepad $env:USERPROFILE\.config\rubit-mcp-mail\config.toml
```

Token storage is simpler on Windows than on Linux: `keyring` talks to the
built-in **Windows Credential Manager** with no extra setup, so the
DBUS/keyring workaround described in
[Register with Claude Desktop](#register-with-claude-desktop) does not apply
— every environment (terminal, Claude Desktop, a scheduled task) can already
reach the same credential store.

When registering with Claude Desktop on Windows, point `command` at the
`.exe` directly in `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rubit-mail": {
      "command": "C:\\path\\to\\rubit-mcp-mail\\.venv\\Scripts\\rubit-mcp-mail.exe",
      "args": ["serve"]
    }
  }
}
```

## Setting up Outlook

Microsoft has permanently retired basic auth for Outlook.com, so app passwords
no longer work — OAuth2 is the only way in. That needs a free Azure app
registration, done once.

### 1. Register the app

1. Go to [portal.azure.com](https://portal.azure.com) → **Microsoft Entra ID** →
   **App registrations** → **New registration**.
2. Name it anything (`rubit-mcp-mail`).
3. Supported account types: **"Accounts in any organizational directory and
   personal Microsoft accounts"**.
   *Required for an outlook.com/hotmail address — the default single-tenant
   option will reject your sign-in.*
4. Leave Redirect URI empty. Click **Register**.
5. **Authentication** → **Advanced settings** → **Allow public client flows**:
   set to **Yes**.
   *Without this the device-code flow fails immediately.*
6. **API permissions** → **Add a permission** → **APIs my organization uses** tab
   → search **Office 365 Exchange Online** → **Delegated permissions** →
   check **`IMAP.AccessAsUser.All`** → **Add permissions**.
7. Copy the **Application (client) ID** from the Overview page.

Those two bolded steps are the ones people miss; both produce confusing errors.
If registering an app is blocked by your organization's policy, sign in to
portal.azure.com with the personal Microsoft account itself (not a work
account) — a personal outlook.com/hotmail account has its own directory that
org policies don't govern.

### 2. Configure

```bash
mkdir -p ~/.config/rubit-mcp-mail
cat > ~/.config/rubit-mcp-mail/config.toml <<'EOF'
download_dir = "~/Downloads/rubit-mcp-mail"

[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "<Application (client) ID from step 7>"
EOF
```

No secrets go in this file. Tokens live in your OS keyring (with a `0600` file
fallback on headless machines).

### 3. Sign in

```bash
./.venv/bin/rubit-mcp-mail auth outlook
```

This prints a code and a URL; approve in your browser. The refresh token is
cached, so this is a one-time step — the server itself only ever refreshes
silently and never prompts.

### 4. Verify

```bash
./.venv/bin/rubit-mcp-mail doctor
```

This checks config, credentials, connectivity, and authentication, then lists
your folders with their detected roles. If this works, the server will too.

### Can't register your own app?

If your Microsoft account genuinely can't register an Azure app (and it isn't
just a work-tenant policy — see the note in step 1), you can use a public
client ID that other open-source mail tools already share for exactly this
purpose instead of registering your own: Thunderbird's,
`9e5f94bc-e8a4-4e73-b8be-63364c29d753`. It's multi-tenant and already has the
`IMAP.AccessAsUser.All` permission granted, so device-code sign-in works
immediately — just paste it in as `client_id`:

```toml
[accounts.outlook]
provider  = "outlook"
email     = "you@outlook.com"
client_id = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
```

Two things to know: the Microsoft consent screen will say **"Thunderbird"** is
requesting access (cosmetic only — the token it grants works the same), and
because this ID is outside our control, Microsoft could disable or rotate it
in the future (it's happened to Thunderbird's client IDs before) — if sign-in
suddenly starts failing, that's the first thing to suspect. Switch to your own
registration above if that happens.

## If Microsoft changes their endpoints

The Outlook IMAP host, OAuth authority URL, and IMAP scope are compiled into
`providers.py` as of when this was built. If Microsoft ever changes one of
them, you don't need to wait for a new release — add a `[providers.outlook]`
table to your own `config.toml` (never tracked by git) with the corrected
value, and it takes effect immediately:

```toml
[providers.outlook]
host = "outlook.office365.com"   # current default, shown for reference

[providers.outlook.oauth]
authority = "https://login.microsoftonline.com/common"
scopes = ["https://outlook.office.com/IMAP.AccessAsUser.All"]
```

Only include the keys you actually need to change. `rubit-mcp-mail doctor`
prints a line naming any overrides currently in effect. This works for any
provider, not just Outlook — `port` and `ssl` are overridable too.

## Other providers

Anything that speaks IMAP with an app password:

```toml
[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
# port   = 993   (default)
```

Then `rubit-mcp-mail auth personal` and paste the app password. Known hosts:
Gmail `imap.gmail.com`, Fastmail `imap.fastmail.com`,
iCloud `imap.mail.me.com`, Yahoo `imap.mail.yahoo.com`.
Gmail and iCloud require an app-specific password, not your login password.

To avoid storing the password at all, set
`RUBIT_MCP_MAIL_PASSWORD_<ACCOUNTNAME>` in the environment instead.

## Register with Claude Code

Run this from the repo root (it resolves the venv path for you):

```bash
claude mcp add rubit-mail --scope user -- "$(pwd)/.venv/bin/rubit-mcp-mail" serve
```

If you'd rather type the path by hand, use one line and no trailing
whitespace — a stray space before the path makes `posix_spawn` look for a
file that doesn't exist:

```bash
claude mcp add rubit-mail --scope user -- /absolute/path/to/rubit-mcp-mail/.venv/bin/rubit-mcp-mail serve
```

## Register with Claude Desktop

Claude Desktop launches MCP servers from the desktop process with a **stripped
environment** — no `DBUS_SESSION_BUS_ADDRESS`, no `XDG_RUNTIME_DIR`. Without
those, `keyring` cannot reach the desktop Secret Service, so the OAuth token
that `rubit-mcp-mail auth` stored in your keyring is invisible to the server and
every account reports "not authenticated" — even though `doctor` in a terminal
says `auth ok`. Pass the session variables explicitly in
`~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rubit-mail": {
      "command": "/absolute/path/to/rubit-mcp-mail/.venv/bin/rubit-mcp-mail",
      "args": ["serve"],
      "env": {
        "HOME": "/home/you",
        "USER": "you",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"
      }
    }
  }
}
```

Use your own uid (`id -u`) in the two `/run/user/...` paths. `HOME`, `USER` and
`PATH` are repeated because some clients replace the default environment rather
than merging with it.

The alternative, if you would rather not depend on the keyring at all, is to set
`RUBIT_MCP_MAIL_NO_KEYRING=1` — in the `env` block **and** in the shell you run
`rubit-mcp-mail auth` from, so both sides use
`~/.config/rubit-mcp-mail/secrets.json` (mode 0600). That puts the refresh token
on disk in plain text; the keyring is the better default.

### Troubleshooting

`serve` logs a startup summary to stderr, which Claude Desktop captures in
`~/.config/Claude/logs/mcp-server-<name>.log` and Claude Code shows with
`claude --mcp-debug`. It names the config path, the secret backend in use, and
whether each account's credential was found:

```
config: /home/you/.config/rubit-mcp-mail/config.toml (found)
secrets: keyring (keyring.backends.SecretService)
account outlook <you@outlook.com> via outlook: credential present (key 'msal-cache:outlook')
```

For more, set `RUBIT_MCP_MAIL_LOG_LEVEL=DEBUG` (and optionally
`RUBIT_MCP_MAIL_LOG_FILE=/tmp/rubit-mail.log`) in the `env` block; at DEBUG the
server also reports each account's live auth status, including why a silent
token refresh failed.

To watch it by hand, run the server in the foreground with the same environment
the client uses:

```bash
env -i HOME="$HOME" USER="$USER" PATH=/usr/local/bin:/usr/bin:/bin \
  RUBIT_MCP_MAIL_LOG_LEVEL=DEBUG ./.venv/bin/rubit-mcp-mail serve
```

If that prints `credential NOT FOUND` while `rubit-mcp-mail doctor` in your
terminal prints `auth ok`, the mismatch is the environment, not the token —
compare the `secrets:` line from each.

## Adding a provider

`src/rubit_mcp_mail/providers.py` is a dict of profiles — host, port, and which auth
strategy to use. Adding a preset is one entry. A provider that needs a non-IMAP
API instead implements the `MailBackend` protocol in
`src/rubit_mcp_mail/backends/base.py`; the tool layer does not change.

## Development

```bash
./.venv/bin/python -m pytest -q
```

## Layout

```
src/rubit_mcp_mail/
  server.py        MCP tool definitions
  __main__.py      CLI: serve | auth | doctor | permissions
  session.py       wires config + auth + backend; attachment path safety
  config.py        TOML config -> Account models
  permissions.py   registry of per-account-toggleable tool names
  permissions_editor.py  pure logic for editing disabled_tools in config.toml
  webui.py         local web GUI for the `permissions` command
  providers.py     provider profile registry
  secrets.py       keyring with 0600-file fallback
  models.py        pydantic models + message handles
  mime.py          BODYSTRUCTURE walking, decoding, HTML->text
  backends/
    base.py        MailBackend protocol
    imap.py        the IMAP implementation
  auth/
    password.py         app passwords
    oauth_microsoft.py  MSAL device-code flow
```

## Notes and limits

- **IMAP search is server-side and fairly basic.** It matches substrings, not
  fuzzy relevance, and there is no "has attachment" criterion in IMAP itself —
  the `has_attachments` field on results comes from the message structure.
- **Bodies are truncated** at 20,000 characters by default to keep long
  newsletters from flooding the context. Raise `max_chars` when you need more.
- **`read_message` only downloads the text parts**, located via `BODYSTRUCTURE`,
  so reading a mail with a 20 MB attachment still costs a few kilobytes. It
  prefers `text/plain` but falls through to `text/html` when the plain part is
  missing or empty — the shape many newsletters take. `body_format` says which
  one you got. HTML is converted to Markdown with reference-style links, so a
  newsletter that repeats the same tracking URL on every headline lists it once
  at the foot instead of inline on every line.
- **Microsoft is actively tightening third-party mail access.** IMAP+OAuth is
  documented and working, but if it were ever withdrawn for consumer accounts,
  the fix is a Graph backend behind the existing `MailBackend` protocol.
