/**
 * The MCP tool surface, mirroring src/rubit_mcp_mail/server.py.
 *
 * All six are reads. `mark_read` / `move_message` do NOT exist - they live in
 * the still-unmerged PR #5, which is what issue #6 wrongly assumed had landed.
 */
export const TOOLS = [
  {
    name: 'list_accounts',
    icon: 'i-lucide-users',
    summary: 'Configured accounts and whether each is authenticated.',
    detail: 'The one tool that is not account-scoped, and the first to call when something reports an auth problem.',
  },
  {
    name: 'list_folders',
    icon: 'i-lucide-folder-tree',
    summary: 'Folders with normalized roles and unread counts.',
    detail: 'Roles are stable across providers, so `junk` works without knowing the server calls it "Junk Email".',
  },
  {
    name: 'list_messages',
    icon: 'i-lucide-inbox',
    summary: 'Browse a folder, newest first, paginated.',
    detail: 'Summaries only. Every result carries an opaque handle you pass to read_message.',
  },
  {
    name: 'search_messages',
    icon: 'i-lucide-search',
    summary: 'Search by text, sender, subject, date range or unread.',
    detail: 'Server-side IMAP search, so it covers the whole folder without downloading it.',
  },
  {
    name: 'read_message',
    icon: 'i-lucide-mail-open',
    summary: 'Full headers, body text and attachment metadata.',
    detail: 'Fetched with BODY.PEEK, so reading does not mark the message as read. HTML becomes Markdown.',
  },
  {
    name: 'get_attachment',
    icon: 'i-lucide-paperclip',
    summary: 'Save one attachment into the download directory.',
    detail: 'The only thing that writes anything, and only ever inside that one directory.',
  },
] as const
