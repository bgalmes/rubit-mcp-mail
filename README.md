# rubit-mcp-mail

A read-only MCP server for reading your mail. Provider-agnostic: it speaks IMAP,
so it works with Outlook.com, Gmail, Fastmail, iCloud, or a self-hosted server —
the provider is a line of config, not a code change.

**Read-only by construction.** Folders are opened with `EXAMINE`, never `SELECT`,
and bodies are fetched with `BODY.PEEK`, so reading a message does not even mark
it as read. There are no send, move, delete, or flag code paths, and a test
asserts none are ever added.

## Quick install

Download the installer for your system from the
[latest release](https://github.com/bgalmes/rubit-mcp-mail/releases/latest) and
run it:

| System | File |
| --- | --- |
| Windows | `rubit-mcp-mail-setup-windows.exe` |
| Linux | `rubit-mcp-mail-setup-linux` — `chmod +x` it first |

Nothing needs to be installed beforehand: Python and every dependency are inside
that one file. A window asks for your provider and email address, signs you in,
and registers the mail server with Claude Desktop and Claude Code if it finds
them — restart Claude Desktop afterwards and your mail is there.

Run it again whenever you want to add a second mailbox or repair a sign-in; it
updates what is already configured rather than replacing it. On a machine with
no desktop (over SSH, say) the same file walks you through it in the terminal.

**A note on antivirus warnings.** Windows Defender or Avast may flag this `.exe`.
This is a known false positive common to unsigned PyInstaller-built applications
— an antivirus heuristic reacting to the pattern of a bundled Python runtime,
not anything this project's code actually does. Proper code-signing is the
durable fix and is tracked as a follow-up, not done yet. In the meantime: report
it to your antivirus vendor as a false positive (Avast has a submission form for
this), or build from source using the instructions below and compare against
what's published here.

Everything below is the manual setup that installer automates — read on if you
want to run from source or something needs fixing by hand.

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

Rather than editing TOML by hand, run `rubit-mcp-mail permissions` — it opens
[the GUI](#the-gui) directly on the permissions page, a grid of accounts and
tools where unchecking a box and saving writes `disabled_tools` back into
`config.toml`.

**A `serve` process caches its config on first read**, so toggling a
permission here does not affect a *running* MCP server (e.g. one launched by
Claude Desktop) until it is restarted.

## The GUI

[Quick install](#quick-install) and `rubit-mcp-mail install` cover first-time
setup. For everything after that — a second mailbox, a typo'd `client_id`, a
changed download directory — this is the editor, and everything in
`config.toml` can be managed from a local web page instead of a text editor:

```bash
rubit-mcp-mail gui
```

It prints a URL (and opens your browser at it) with pages to:

- **See every account at a glance** — provider, server, and whether it is signed
  in, with the same diagnosis `doctor` gives.
- **Add, edit, and remove accounts** — pick Outlook or any other IMAP server,
  fill in the fields, and the form is validated before anything is written. The
  Outlook page offers Thunderbird's shared client ID for accounts that
  [can't register their own Azure app](#cant-register-your-own-app).
- **Sign in** — the password prompt for app-password providers, and the full
  device-code flow for Outlook, without dropping to a terminal. Credentials go
  to the same keyring (or `0600` file) the CLI uses; the config file never
  holds a secret.
- **Set the download directory** and the per-account tool permissions.
- **Edit provider overrides** — the `[providers.*]` tables described under
  [If Microsoft changes their endpoints](#if-microsoft-changes-their-endpoints),
  without writing TOML table syntax.
- **Run doctor** and read the result in the page.

It reads and writes the very same file the CLI and server use, through the same
parser: a hand-edited config opens correctly in the GUI, saving one account
leaves every other line, comment and ordering untouched, and a change that
would not load is refused rather than written. Use `--port` for a fixed port
and `--no-browser` to skip opening one.

**On access:** the page binds to `127.0.0.1` only, and the URL it prints carries
a random token minted at startup (exchanged for a session cookie on first
load). Requests without it are refused, as are requests arriving under a
non-loopback hostname or a form posted from another site. Open the URL as
printed; the token is what keeps other pages in your browser out.

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
— `Path.home() / ".config"` resolves there on Windows too. The simplest way to
create it is `.venv\Scripts\rubit-mcp-mail.exe gui`, which writes the file for
you; to do it by hand, use `mkdir` and a text editor instead of the `cat`
heredoc the [Configure](#2-configure) section shows:

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

Two ways avoid writing this by hand: `rubit-mcp-mail install` walks a first-time
setup end to end (config, sign-in, and registering with Claude), and
`rubit-mcp-mail gui` opens [the config editor](#the-gui) for this and every
later change. By hand it is:

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
silently and never prompts. The same flow runs in the GUI if you would rather
not use a terminal.

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

Only include the keys you actually need to change; the GUI's Providers page
writes the same table from a form. `rubit-mcp-mail doctor` prints a line naming
any overrides currently in effect. This works for any
provider, not just Outlook — `port` and `ssl` are overridable too.

## Other providers

Anything that speaks IMAP with an app password. Add it in [the GUI](#the-gui),
or by hand:

```toml
[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
# port   = 993   (default)
```

Then `rubit-mcp-mail auth personal` and paste the app password (or do both from
the GUI). Known hosts:
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

### Building the installers

`.github/workflows/release.yml` builds them for Windows and Linux and attaches
them to every published release. The same two steps build one locally — the
server executable first, then the installer that carries it:

```bash
./.venv/bin/python -m pip install -e ".[build]"
./.venv/bin/pyinstaller --onefile --name rubit-mcp-mail \
  --version-file packaging/version_info.txt packaging/cli_entry.py
./.venv/bin/pyinstaller --onefile --windowed --name rubit-mcp-mail-setup \
  --version-file packaging/version_info.txt \
  --add-binary "dist/rubit-mcp-mail:." packaging/setup_entry.py
```

On Windows the `--add-binary` separator is `;` rather than `:`.
`packaging/version_info.txt` gives both binaries a real product name and
description instead of being completely anonymous — see the antivirus note
above; Windows-only, silently ignored on Linux. The wizard unpacks the server
executable into `~/.local/share/rubit-mcp-mail/bin`
(`%LOCALAPPDATA%\Programs\rubit-mcp-mail` on Windows) and registers that path,
so the installer itself can be deleted afterwards.

## Layout

```
src/rubit_mcp_mail/
  server.py        MCP tool definitions
  __main__.py      CLI: serve | install | auth | doctor | gui
  installer.py     setup wizard: writes config, signs in, registers with Claude
  installer_gui.py the setup window (tkinter), falling back to the terminal
  claude_registration.py  claude_desktop_config.json / `claude mcp add`
  session.py       wires config + auth + backend; attachment path safety
  config.py        TOML config -> Account models
  diagnostics.py   the doctor checks, as data (shared by the CLI and the GUI)
  permissions.py   registry of per-account-toggleable tool names
  config_editor.py every write to config.toml: comment-preserving, validated
  webui.py         local web GUI: routing and access control
  webui_pages.py   local web GUI: HTML
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
