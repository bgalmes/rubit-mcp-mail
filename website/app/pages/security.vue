<script setup lang="ts">
useSeoMeta({
  title: 'Security',
  description:
    'Why rubit-mcp-mail cannot modify your mail: EXAMINE instead of SELECT, BODY.PEEK on '
    + 'every fetch, no write code paths, and a test that fails if anyone adds one.',
})

const REPO = 'https://github.com/bgalmes/rubit-mcp-mail/blob/main'

const GUARANTEES = [
  {
    icon: 'i-lucide-eye',
    title: 'Folders are opened with EXAMINE',
    body: 'IMAP has two ways to open a mailbox: SELECT, which gives read-write access, and '
      + 'EXAMINE, which is read-only at the protocol level. Every folder this server opens '
      + 'uses EXAMINE. The server is not choosing to behave — the session it negotiated '
      + 'cannot carry a write.',
    evidence: { label: 'backends/imap.py', href: `${REPO}/src/rubit_mcp_mail/backends/imap.py` },
  },
  {
    icon: 'i-lucide-mail-open',
    title: 'Bodies are fetched with BODY.PEEK',
    body: 'A normal IMAP fetch sets the \\Seen flag as a side effect — which is how a mail '
      + 'client marks things read. BODY.PEEK is the variant that does not. Your assistant '
      + 'can read a thread and your unread count will not move.',
    evidence: { label: 'mime.py', href: `${REPO}/src/rubit_mcp_mail/mime.py` },
  },
  {
    icon: 'i-lucide-ban',
    title: 'There are no write code paths',
    body: 'No send, no move, no delete, no flag, no append, no expunge — not disabled behind '
      + 'a flag, absent. The MailBackend protocol every backend implements states the rule '
      + 'in its own docstring: no implementation may set flags, move, delete, append, or expunge.',
    evidence: { label: 'backends/base.py', href: `${REPO}/src/rubit_mcp_mail/backends/base.py` },
  },
  {
    icon: 'i-lucide-flask-conical',
    title: 'A test keeps it that way',
    body: 'The fake IMAP server the suite runs against raises on every mutating call, and a '
      + 'separate regression test scans the backend for them. Adding a write does not quietly '
      + 'ship — it fails CI.',
    evidence: { label: 'tests/fake_imap.py', href: `${REPO}/tests/fake_imap.py` },
  },
]

const HANDLING = [
  {
    icon: 'i-lucide-house',
    title: 'Your mail never leaves your machine',
    body: 'The server runs locally and talks to your assistant over stdio. There is no cloud '
      + 'component, no relay, and no account to sign up for. Mail goes from your provider to '
      + 'your machine and no further.',
  },
  {
    icon: 'i-lucide-key-round',
    title: 'Credentials live in the OS keyring',
    body: 'Tokens and app passwords go to the system credential store — Secret Service on '
      + 'Linux, Credential Manager on Windows. Where no keyring is reachable they fall back '
      + 'to a file created mode 0600 from the start. config.toml never holds a secret.',
  },
  {
    icon: 'i-lucide-signal-zero',
    title: 'No telemetry, of any kind',
    body: 'Nothing is counted, sampled or phoned home. The only network connections it makes '
      + 'are to your mail provider and, for Outlook, to Microsoft’s sign-in endpoint.',
  },
  {
    icon: 'i-lucide-folder-lock',
    title: 'Attachments cannot escape their directory',
    body: 'get_attachment is the only thing that writes anything. Filenames are sanitized, '
      + 'cannot traverse upwards out of the configured download directory, and never '
      + 'overwrite an existing file.',
  },
  {
    icon: 'i-lucide-scissors',
    title: 'Only the text parts are downloaded',
    body: 'Bodies are located via BODYSTRUCTURE and truncated at 20,000 characters by default, '
      + 'so a mail with a 20 MB attachment costs kilobytes and a newsletter cannot flood the '
      + 'context.',
  },
  {
    icon: 'i-lucide-lock',
    title: 'You can narrow it further',
    body: 'Any account-scoped tool can be switched off per account with disabled_tools — '
      + 'keeping attachments off a shared mailbox, say, or leaving a work account listed but '
      + 'unreadable.',
  },
]

const LIMITS = [
  'The installers are **unsigned**, so Windows Defender and Avast may flag them. That is a '
  + 'known false positive for PyInstaller binaries, and code signing is a real follow-up, not '
  + 'done yet. Every published SHA-256 is on the changelog so you can verify what you downloaded.',
  'This does not constrain **what your assistant does with what it reads**. It guarantees your '
  + 'mailbox is not modified; it cannot guarantee a model will not quote a message back to you '
  + 'in a context you did not expect.',
  'A **prompt injection in an email** is a real risk for any tool that feeds mail to a model. '
  + 'Reading is safe for your mailbox; acting on what you read is your assistant’s '
  + 'business, not this server’s.',
  'Your **mail provider still sees ordinary IMAP access** from your machine, and for Outlook, '
  + 'Microsoft sees an OAuth grant against your own Azure app registration.',
  'The site you are reading is static hosting on GitHub Pages, which does not let a project '
  + 'set response headers — so no claims are made about the security headers of this page.',
]
</script>

<template>
  <div>
    <section class="relative isolate overflow-hidden">
      <AuroraBackdrop />
      <UContainer class="relative z-10 py-20 sm:py-28">
        <div class="mx-auto max-w-3xl text-center">
          <UBadge color="primary" variant="subtle" label="Security" class="mb-6" />
          <h1 class="text-4xl font-semibold tracking-tight text-highlighted sm:text-5xl">
            Read-only by construction
          </h1>
          <p class="mt-6 text-lg text-muted">
            Handing an assistant your mailbox is a real decision. The answer here is not a
            setting you have to trust — it is that the code to modify your mail was never
            written, and a test fails the moment someone writes it.
          </p>
        </div>
      </UContainer>
    </section>

    <div class="rule-fade" />

    <UContainer class="py-16 sm:py-24">
      <div class="mx-auto max-w-3xl">
        <h2 class="text-2xl font-semibold tracking-tight text-highlighted sm:text-3xl">
          The four guarantees
        </h2>
        <p class="mt-3 text-muted">
          Each one is a property of the code, with the file that carries it.
        </p>

        <ul class="mt-10 space-y-6">
          <li
            v-for="item in GUARANTEES"
            :key="item.title"
            class="rounded-xl border border-default/70 bg-elevated/30 p-6"
          >
            <div class="flex items-center gap-3">
              <UIcon :name="item.icon" class="size-5 shrink-0 text-primary" />
              <h3 class="font-semibold text-highlighted">{{ item.title }}</h3>
            </div>
            <p class="mt-3 text-sm text-muted">{{ item.body }}</p>
            <UButton
              :to="item.evidence.href"
              target="_blank"
              rel="noopener"
              color="neutral"
              variant="link"
              size="xs"
              class="mt-3 px-0 font-mono"
              trailing-icon="i-lucide-external-link"
              :label="item.evidence.label"
            />
          </li>
        </ul>

        <h2 class="mt-20 text-2xl font-semibold tracking-tight text-highlighted sm:text-3xl">
          How your data is handled
        </h2>
        <div class="mt-10 grid gap-4 sm:grid-cols-2">
          <div
            v-for="item in HANDLING"
            :key="item.title"
            class="rounded-xl border border-default/70 bg-elevated/30 p-5"
          >
            <UIcon :name="item.icon" class="size-5 text-primary" />
            <h3 class="mt-3 text-sm font-semibold text-highlighted">{{ item.title }}</h3>
            <p class="mt-2 text-xs text-muted">{{ item.body }}</p>
          </div>
        </div>

        <h2 class="mt-20 text-2xl font-semibold tracking-tight text-highlighted sm:text-3xl">
          What this does <em>not</em> protect against
        </h2>
        <p class="mt-3 text-muted">
          A security page that only lists strengths is marketing. These are the real edges.
        </p>
        <ul class="mt-8 space-y-4">
          <li
            v-for="(limit, i) in LIMITS"
            :key="i"
            class="flex gap-3 rounded-lg border border-default/50 bg-elevated/20 p-4"
          >
            <UIcon name="i-lucide-alert-triangle" class="mt-0.5 size-4 shrink-0 text-warning" />
            <MDC :value="limit" class="text-sm text-muted [&_p]:m-0" />
          </li>
        </ul>

        <div class="mt-16 rounded-xl border border-primary/30 bg-primary/5 p-6">
          <h2 class="flex items-center gap-2 text-lg font-semibold text-highlighted">
            <UIcon name="i-lucide-shield-alert" class="size-5 text-primary" />
            Reporting a vulnerability
          </h2>
          <p class="mt-3 text-sm text-muted">
            Please don't open a public issue first. Use the contact form and pick
            <strong>Security disclosure</strong> — it reaches a person directly.
          </p>
          <UButton to="/contact" class="mt-5" trailing-icon="i-lucide-arrow-right" label="Report privately" />
        </div>
      </div>
    </UContainer>
  </div>
</template>
