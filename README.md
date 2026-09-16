# rubit-mcp-mail

<!-- mcp-name: io.github.bgalmes/rubit-mcp-mail -->

[![CI](https://github.com/bgalmes/rubit-mcp-mail/actions/workflows/ci.yml/badge.svg)](https://github.com/bgalmes/rubit-mcp-mail/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/bgalmes/rubit-mcp-mail)](https://github.com/bgalmes/rubit-mcp-mail/releases)
[![PyPI](https://img.shields.io/pypi/v/rubit-mcp-mail)](https://pypi.org/project/rubit-mcp-mail/)
[![Python](https://img.shields.io/pypi/pyversions/rubit-mcp-mail)](https://pypi.org/project/rubit-mcp-mail/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/bgalmes/rubit-mcp-mail/blob/main/LICENSE)

A read-only MCP server for reading your mail. Provider-agnostic: it speaks IMAP,
so it works with Outlook.com, Gmail, Fastmail, iCloud, or a self-hosted server —
the provider is a line of config, not a code change.

**Read-only by construction.** Folders are opened with `EXAMINE`, never `SELECT`,
and bodies are fetched with `BODY.PEEK`, so reading a message does not even mark
it as read. There are no send, move, delete, or flag code paths, and a test
asserts none are ever added.

📖 **Full documentation: <https://bgalmes.github.io/rubit-mcp-mail/>**

## Quick install

Download the installer for your system from the
[latest release](https://github.com/bgalmes/rubit-mcp-mail/releases) and run it:

| System | File |
| --- | --- |
| Windows | `rubit-mcp-mail-setup-windows.exe` |
| Linux | `rubit-mcp-mail-setup-linux` — `chmod +x` it first |

Nothing needs to be installed beforehand: Python and every dependency are inside
that one file. A window asks for your provider and email address, signs you in,
and registers the mail server with Claude Desktop and Claude Code if it finds
them — restart Claude Desktop afterwards and your mail is there. It also leaves
you a **rubit-mcp-mail Settings** shortcut for everything you want to change
later. No terminal, at any point.

There is no macOS installer; on a Mac, install from source (below).

**A note on antivirus warnings.** Windows Defender or Avast may flag this `.exe`.
This is a known false positive common to unsigned PyInstaller-built applications,
not anything this project's code does — see
[the install guide](https://bgalmes.github.io/rubit-mcp-mail/docs/install/installer)
for what to do about it. Every published SHA-256 is listed on
[the changelog](https://bgalmes.github.io/rubit-mcp-mail/changelog).

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

Full arguments and return shapes:
[Tools reference](https://bgalmes.github.io/rubit-mcp-mail/docs/reference/tools).

## Install with pip

If you already have Python 3.11+ and would rather not run an installer:

```bash
pip install rubit-mcp-mail
rubit-mcp-mail install      # the same setup wizard, from the terminal
```

## Install from source

```bash
cd /path/to/rubit-mcp-mail
conda create -p ./.venv python=3.12 pip -y     # this machine has no python3-venv
./.venv/bin/python -m pip install -e .
```

Then configure an account, `rubit-mcp-mail auth <account>`, and
`rubit-mcp-mail doctor`. The Windows variant and the full walkthrough are in
[Install from source](https://bgalmes.github.io/rubit-mcp-mail/docs/install/from-source).

## Setting up a mailbox

Microsoft has retired basic auth for Outlook.com, so **Outlook needs a free
Azure app registration** — seven steps, done once, written out in
[Setting up Outlook](https://bgalmes.github.io/rubit-mcp-mail/docs/providers/outlook).
Everything else takes an app password:

```toml
[accounts.personal]
provider = "generic"
email    = "you@fastmail.com"
host     = "imap.fastmail.com"
```

Known hosts: Gmail `imap.gmail.com`, Fastmail `imap.fastmail.com`,
iCloud `imap.mail.me.com`, Yahoo `imap.mail.yahoo.com`. Gmail and iCloud require
an app-specific password, not your login password.

### Can't register your own Azure app?

If your Microsoft account genuinely can't register one, you can use the public
client ID that other open-source mail tools already share for this purpose —
Thunderbird's, `9e5f94bc-e8a4-4e73-b8be-63364c29d753`. Paste it in as
`client_id`. The consent screen will say "Thunderbird", and because the ID is
outside our control Microsoft could rotate it. Details and caveats:
[Can't register your own app?](https://bgalmes.github.io/rubit-mcp-mail/docs/providers/outlook#cant-register-your-own-app).

## Permissions

Any account-scoped tool can be forbidden for a given account with
`disabled_tools` in `config.toml`, or by unticking a box on the settings
window's Permissions tab. A blocked call returns a plain `Error: ...` string to
the model rather than failing silently. See
[Permissions](https://bgalmes.github.io/rubit-mcp-mail/docs/reference/permissions).

## Registering with Claude

```bash
claude mcp add rubit-mail --scope user -- "$(pwd)/.venv/bin/rubit-mcp-mail" serve
```

Claude Desktop needs a JSON entry instead, and on Linux it needs the session
environment passed explicitly or the keyring is unreachable —
[Register with Claude](https://bgalmes.github.io/rubit-mcp-mail/docs/install/claude-clients)
has both, and
[Troubleshooting](https://bgalmes.github.io/rubit-mcp-mail/docs/guides/troubleshooting)
has the logs.

## Development

```sh
ruff check .
ruff format --check .
pyright
pytest -q
```

Those are the same checks CI runs. Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/) and drive automatic
versioning — see [CONTRIBUTING.md](https://github.com/bgalmes/rubit-mcp-mail/blob/main/CONTRIBUTING.md)
and [AGENTS.md](https://github.com/bgalmes/rubit-mcp-mail/blob/main/AGENTS.md). Building the installers and adding a provider are covered
in [Contributing](https://bgalmes.github.io/rubit-mcp-mail/docs/about/contributing).

### The website

`website/` holds the documentation site (Nuxt), deployed to GitHub Pages by
`.github/workflows/deploy-website.yml`. It is the source of truth for the docs;
this README is deliberately the short version.

> [!IMPORTANT]
> Website commits must **not** use `feat:` or `fix:`. `python-semantic-release`
> parses the commit *type*, not the scope, so `feat(site): …` would bump the
> Python package and cut an installer release. Use `docs(site):`,
> `chore(site):` or `ci(site):`.

## Layout

```
src/rubit_mcp_mail/
  server.py        MCP tool definitions
  __main__.py      CLI: serve | install | auth | doctor | gui
  installer.py     setup wizard: writes config, signs in, registers with Claude
  installer_gui.py the setup window (tkinter), falling back to the terminal
  shortcuts.py     Start Menu / Desktop / .desktop entries for the GUI
  claude_registration.py  claude_desktop_config.json / `claude mcp add`
  session.py       wires config + auth + backend; attachment path safety
  config.py        TOML config -> Account models
  diagnostics.py   the doctor checks, as data (shared by the CLI and the GUI)
  permissions.py   registry of per-account-toggleable tool names
  config_editor.py every write to config.toml: comment-preserving, validated
  config_gui.py    the settings window (tkinter): accounts, permissions, doctor
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
website/           the documentation site (Nuxt); see "The website" above
```

## Releasing

Every merge to `main` prepares a release PR carrying only the `pyproject.toml`
and `CHANGELOG.md` diff; a maintainer merges it by hand, which publishes the
prerelease and builds the installers; `promote-release.yml` is dispatched
manually to drop the `-rc.N` suffix. The human merge is load-bearing — GitHub
raises no events for anything `GITHUB_TOKEN` does. Full flow:
[CONTRIBUTING.md](https://github.com/bgalmes/rubit-mcp-mail/blob/main/CONTRIBUTING.md)
and [How releases work](https://bgalmes.github.io/rubit-mcp-mail/docs/about/contributing#how-a-release-happens).

## Notes and limits

IMAP search is substring-based, bodies are truncated at 20,000 characters, only
text parts are downloaded, and Microsoft is actively tightening third-party mail
access. The details are in
[Notes and limits](https://bgalmes.github.io/rubit-mcp-mail/docs/about/limits).
