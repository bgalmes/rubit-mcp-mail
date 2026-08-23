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

## Install

```bash
cd /path/to/rubit-mcp-mail
conda create -p ./.venv python=3.12 pip -y     # this machine has no python3-venv
./.venv/bin/python -m pip install -e .
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

```bash
claude mcp add rubit-mail --scope user -- \
  /path/to/rubit-mcp-mail/.venv/bin/rubit-mcp-mail serve
```

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
  __main__.py      CLI: serve | auth | doctor
  session.py       wires config + auth + backend; attachment path safety
  config.py        TOML config -> Account models
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
- **`read_message` only downloads the text part**, located via `BODYSTRUCTURE`,
  so reading a mail with a 20 MB attachment still costs a few kilobytes.
- **Microsoft is actively tightening third-party mail access.** IMAP+OAuth is
  documented and working, but if it were ever withdrawn for consumer accounts,
  the fix is a Graph backend behind the existing `MailBackend` protocol.
