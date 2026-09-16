<script setup lang="ts">
import { TOOLS } from '~/utils/tools'

const { recommended, hasStable } = useReleases()

const { canonical } = usePageSeo({
  title: 'Let Claude read your mail. Nothing else.',
  description:
    'A read-only MCP server for your mail. Provider-agnostic IMAP — Outlook, Gmail, '
    + 'Fastmail, iCloud or self-hosted — that never marks a message as read.',
})

// The site shipped with no structured data at all. SoftwareApplication is the
// schema.org type search engines understand for a downloadable tool, and it is
// what lets a result carry the licence and price rather than just a title.
useHead({
  script: [{
    type: 'application/ld+json',
    innerHTML: JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'SoftwareApplication',
      'name': 'rubit-mcp-mail',
      'applicationCategory': 'DeveloperApplication',
      'operatingSystem': 'Windows, Linux, macOS',
      'url': canonical,
      'description':
        'A read-only MCP server for your mail. Provider-agnostic IMAP — Outlook, Gmail, '
        + 'Fastmail, iCloud or self-hosted — that never marks a message as read.',
      'codeRepository': 'https://github.com/bgalmes/rubit-mcp-mail',
      'programmingLanguage': 'Python',
      'license': 'https://github.com/bgalmes/rubit-mcp-mail/blob/main/LICENSE',
      'downloadUrl': 'https://github.com/bgalmes/rubit-mcp-mail/releases',
      // Free, but schema.org needs it said explicitly to render as such.
      'offers': { '@type': 'Offer', 'price': '0', 'priceCurrency': 'USD' },
    }),
  }],
})

// simple-icons has no Fastmail glyph, so that one falls back to a lucide mark.
const PROVIDERS = [
  { name: 'Outlook.com', icon: 'i-simple-icons-microsoftoutlook' },
  { name: 'Gmail', icon: 'i-simple-icons-gmail' },
  { name: 'Fastmail', icon: 'i-lucide-mail' },
  { name: 'iCloud', icon: 'i-simple-icons-icloud' },
  { name: 'Yahoo', icon: 'i-simple-icons-yahoo' },
  { name: 'Self-hosted', icon: 'i-lucide-server' },
]

const GUARANTEES = [
  {
    icon: 'i-lucide-eye',
    title: 'EXAMINE, never SELECT',
    description: 'Folders are opened read-only at the protocol level. The server cannot write even by accident.',
  },
  {
    icon: 'i-lucide-mail-open',
    title: 'BODY.PEEK on every fetch',
    description: 'Reading a message does not set \\Seen. Your unread count is exactly where you left it.',
  },
  {
    icon: 'i-lucide-ban',
    title: 'No write code paths exist',
    description: 'There is no send, move, delete, flag or expunge anywhere in the codebase. Not disabled — absent.',
  },
  {
    icon: 'i-lucide-flask-conical',
    title: 'A test keeps it that way',
    description: 'The fake IMAP server raises on every mutating call, so adding one fails the suite.',
  },
]
</script>

<template>
  <div>
    <!-- ── Hero ────────────────────────────────────────────────────────── -->
    <section class="relative isolate overflow-hidden">
      <AuroraBackdrop />

      <UContainer class="relative z-10 py-20 sm:py-28 lg:py-36">
        <div class="flex flex-col items-center text-center">
          <UBadge
            v-if="recommended"
            color="neutral"
            variant="subtle"
            class="mb-6 font-mono"
            :ui="{ base: 'rounded-full px-3 py-1' }"
          >
            <span class="text-primary">{{ recommended.tag }}</span>
            <span class="mx-1.5 text-muted" aria-hidden="true">·</span>
            <span class="text-muted">{{ hasStable ? 'latest' : 'pre-release' }}</span>
          </UBadge>

          <h1 class="max-w-3xl text-4xl font-semibold tracking-tight text-highlighted sm:text-6xl">
            Let Claude read your mail.
            <span class="text-primary">Nothing else.</span>
          </h1>

          <p class="mt-6 max-w-2xl text-lg text-muted">
            A read-only MCP server that speaks IMAP, so it works with Outlook.com, Gmail,
            Fastmail, iCloud or your own server. Reading a message doesn't even mark it as read.
          </p>

          <div id="download" class="mt-10 scroll-mt-24">
            <DownloadButton />
          </div>

          <TerminalWindow title="rubit-mcp-mail doctor" class="mt-16 w-full max-w-2xl text-left">
<span class="text-muted">$</span> rubit-mcp-mail doctor
config: ~/.config/rubit-mcp-mail/config.toml <span class="text-muted">(found)</span>
secrets: keyring <span class="text-muted">(keyring.backends.SecretService)</span>

account <span class="text-primary">outlook</span> &lt;you@outlook.com&gt; via outlook
  <span class="text-emerald-400">✓</span> config       <span class="text-emerald-400">✓</span> credential
  <span class="text-emerald-400">✓</span> connectivity <span class="text-emerald-400">✓</span> auth ok

folders: inbox <span class="text-muted">(1204/3)</span>  sent  drafts  junk  trash  archive
          </TerminalWindow>
        </div>
      </UContainer>
    </section>

    <div class="rule-fade" />

    <!-- ── Tools ───────────────────────────────────────────────────────── -->
    <section class="py-20 sm:py-28">
      <UContainer>
        <div class="max-w-2xl">
          <h2 class="text-3xl font-semibold tracking-tight text-highlighted sm:text-4xl">
            Six tools. Every one a read.
          </h2>
          <p class="mt-4 text-muted">
            There is no delete tool, no move tool, and no send tool — and none are planned.
            Each of these can be switched off per account if you want the surface even smaller.
          </p>
        </div>

        <div class="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <ToolCard v-for="tool in TOOLS" :key="tool.name" v-bind="tool" />
        </div>

        <div class="mt-8">
          <UButton
            to="/docs/reference/tools"
            color="neutral"
            variant="subtle"
            trailing-icon="i-lucide-arrow-right"
            label="Full arguments and return shapes"
          />
        </div>
      </UContainer>
    </section>

    <div class="rule-fade" />

    <!-- ── Providers ───────────────────────────────────────────────────── -->
    <section class="py-20 sm:py-24">
      <UContainer>
        <div class="flex flex-col items-center text-center">
          <h2 class="text-3xl font-semibold tracking-tight text-highlighted sm:text-4xl">
            Your provider, not ours.
          </h2>
          <p class="mt-4 max-w-2xl text-muted">
            It speaks IMAP, so the provider is a line of config rather than a code change.
            Outlook signs in with OAuth2; everything else takes an app password.
          </p>

          <ul class="mt-12 flex flex-wrap items-center justify-center gap-x-10 gap-y-6">
            <li
              v-for="provider in PROVIDERS"
              :key="provider.name"
              class="flex items-center gap-2.5 text-muted transition-colors hover:text-default"
            >
              <UIcon :name="provider.icon" class="size-5" />
              <span class="text-sm font-medium">{{ provider.name }}</span>
            </li>
          </ul>
        </div>
      </UContainer>
    </section>

    <div class="rule-fade" />

    <!-- ── The guarantee ───────────────────────────────────────────────── -->
    <section class="py-20 sm:py-28">
      <UContainer>
        <div class="grid gap-12 lg:grid-cols-2 lg:gap-16">
          <div>
            <UBadge color="primary" variant="subtle" label="Read-only by construction" class="mb-5" />
            <h2 class="text-3xl font-semibold tracking-tight text-highlighted sm:text-4xl">
              Not "we promise". Structurally incapable.
            </h2>
            <p class="mt-5 text-muted">
              Handing an assistant your mailbox is a real decision. The answer here isn't a
              setting you have to trust — it's that the code to modify your mail was never
              written, and a test in CI fails the moment someone writes it.
            </p>
            <UButton
              to="/security"
              class="mt-8"
              color="neutral"
              variant="subtle"
              trailing-icon="i-lucide-arrow-right"
              label="Read the security model"
            />
          </div>

          <ul class="grid gap-4 sm:grid-cols-2">
            <li
              v-for="item in GUARANTEES"
              :key="item.title"
              class="rounded-xl border border-default/70 bg-elevated/40 p-5 backdrop-blur-sm"
            >
              <UIcon :name="item.icon" class="size-5 text-primary" />
              <h3 class="mt-3 text-sm font-semibold text-highlighted">{{ item.title }}</h3>
              <p class="mt-1.5 text-xs text-muted">{{ item.description }}</p>
            </li>
          </ul>
        </div>
      </UContainer>
    </section>

    <div class="rule-fade" />

    <!-- ── CTA ─────────────────────────────────────────────────────────── -->
    <section class="relative isolate overflow-hidden py-20 sm:py-28">
      <UContainer class="relative z-10">
        <div class="flex flex-col items-center text-center">
          <h2 class="max-w-2xl text-3xl font-semibold tracking-tight text-highlighted sm:text-4xl">
            One file. No terminal.
          </h2>
          <p class="mt-4 max-w-xl text-muted">
            Python and every dependency are inside the installer. It asks for your mailbox,
            signs you in, and registers itself with Claude Desktop and Claude Code.
          </p>
          <div class="mt-10">
            <DownloadButton size="lg" />
          </div>
        </div>
      </UContainer>
    </section>
  </div>
</template>
