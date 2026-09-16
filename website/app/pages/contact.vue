<script setup lang="ts">
import { z } from 'zod'
import type { FormSubmitEvent } from '@nuxt/ui'

usePageSeo({
  title: 'Contact',
  description: 'Questions, bug reports and security disclosures.',
  robots: 'noindex, follow',
})

const accessKey = useRuntimeConfig().public.web3formsKey as string
const configured = computed(() => Boolean(accessKey))

const TOPICS = ['Question', 'Bug report', 'Security disclosure', 'Something else'] as const

const schema = z.object({
  name: z.string().min(2, 'Please tell us who you are').max(80),
  email: z.string().email('That does not look like an email address'),
  topic: z.enum(TOPICS),
  message: z.string().min(20, 'A few more words, please').max(4000),
})
type Schema = z.output<typeof schema>

const state = reactive<Partial<Schema>>({
  name: undefined,
  email: undefined,
  topic: 'Question',
  message: undefined,
})

// Layer 1: honeypot. Web3Forms reserves this exact field name and rejects a
// submission server-side when it arrives ticked.
const botcheck = ref(false)

// Layer 2: time trap. Bots submit the instant the DOM exists.
const MIN_DWELL_MS = 3000
const mountedAt = ref(0)
onMounted(() => { mountedAt.value = Date.now() })

// Layer 3: hCaptcha.
const captchaEl = ref<HTMLElement | null>(null)
const captcha = useHCaptcha(captchaEl)

const status = ref<'idle' | 'sending' | 'sent' | 'error'>('idle')
const notice = ref('')
const toast = useToast()

async function onSubmit(event: FormSubmitEvent<Schema>) {
  // A human never sees this box, let alone ticks it. Pretend it worked rather
  // than telling the bot which check caught it.
  if (botcheck.value) {
    status.value = 'sent'
    return
  }

  if (Date.now() - mountedAt.value < MIN_DWELL_MS) {
    notice.value = 'That was quick — give it a second and send again.'
    mountedAt.value = 0 // a genuine second attempt sails through
    status.value = 'error'
    return
  }

  const captchaToken = captcha.token()
  if (!captchaToken && !captcha.failed.value) {
    notice.value = 'Please complete the "I am human" check first.'
    status.value = 'error'
    return
  }

  status.value = 'sending'
  try {
    const res = await $fetch<{ success: boolean, message?: string }>(
      'https://api.web3forms.com/submit',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: {
          access_key: accessKey,
          subject: `[rubit-mcp-mail] ${event.data.topic} from ${event.data.name}`,
          from_name: 'rubit-mcp-mail website',
          replyto: event.data.email,
          name: event.data.name,
          email: event.data.email,
          topic: event.data.topic,
          message: event.data.message,
          botcheck: false,
          'h-captcha-response': captchaToken,
        },
      },
    )
    if (!res.success) throw new Error(res.message || 'The form service rejected the message')

    status.value = 'sent'
    toast.add({ title: 'Message sent', description: 'Thanks — every message gets read.', color: 'success', icon: 'i-lucide-check' })
    Object.assign(state, { name: undefined, email: undefined, topic: 'Question', message: undefined })
  } catch (error: unknown) {
    status.value = 'error'
    const e = error as { data?: { message?: string }, message?: string }
    notice.value = e?.data?.message || e?.message || 'Something went wrong. Please try again.'
  } finally {
    captcha.reset()
    mountedAt.value = Date.now()
  }
}
</script>

<template>
  <UContainer class="py-16 sm:py-24">
    <div class="mx-auto max-w-2xl">
      <UPageHeader
        title="Get in touch"
        description="Questions, bug reports, and security disclosures. Every message is read by a person."
      />

      <UAlert
        v-if="!configured"
        class="mt-8"
        color="warning"
        variant="subtle"
        icon="i-lucide-triangle-alert"
        title="The form isn't wired up yet"
        description="No form key is configured for this build. Open an issue on GitHub in the meantime."
        :actions="[{ label: 'Open an issue', to: 'https://github.com/bgalmes/rubit-mcp-mail/issues', target: '_blank', color: 'neutral', variant: 'subtle' }]"
      />

      <UPageCard v-else variant="subtle" class="mt-8">
        <UForm :schema="schema" :state="state" class="space-y-5" @submit="onSubmit">
          <!-- Honeypot. Never focusable, never announced, never visible. -->
          <input
            v-model="botcheck"
            type="checkbox"
            name="botcheck"
            class="hidden"
            style="display: none"
            tabindex="-1"
            autocomplete="off"
            aria-hidden="true"
          >

          <div class="grid gap-5 sm:grid-cols-2">
            <UFormField label="Name" name="name" required>
              <UInput v-model="state.name" autocomplete="name" class="w-full" />
            </UFormField>
            <UFormField label="Email" name="email" required hint="Only used to reply">
              <UInput v-model="state.email" type="email" autocomplete="email" class="w-full" />
            </UFormField>
          </div>

          <UFormField label="Topic" name="topic" required>
            <USelectMenu v-model="state.topic" :items="[...TOPICS]" class="w-full" />
          </UFormField>

          <UFormField label="Message" name="message" required>
            <UTextarea v-model="state.message" :rows="8" class="w-full" />
          </UFormField>

          <ClientOnly>
            <div ref="captchaEl" class="min-h-[78px]" />
            <UAlert
              v-if="captcha.failed.value"
              color="warning"
              variant="subtle"
              icon="i-lucide-shield-alert"
              title="Couldn't load the human check"
              description="A browser extension may be blocking it. You can also open a GitHub issue instead."
            />
          </ClientOnly>

          <UAlert
            v-if="status === 'error'"
            color="error"
            variant="subtle"
            icon="i-lucide-triangle-alert"
            :description="notice"
          />
          <UAlert
            v-else-if="status === 'sent'"
            color="success"
            variant="subtle"
            icon="i-lucide-check"
            title="Message sent"
            description="Thanks — every message gets read."
          />

          <div class="flex flex-wrap items-center gap-3">
            <UButton
              type="submit"
              size="lg"
              icon="i-lucide-send"
              :loading="status === 'sending'"
              :disabled="status === 'sent'"
              label="Send"
            />
            <span class="text-xs text-muted">
              Protected by hCaptcha. No tracking, no newsletter.
            </span>
          </div>
        </UForm>
      </UPageCard>

      <div class="mt-10 grid gap-4 sm:grid-cols-2">
        <UPageCard
          icon="i-simple-icons-github"
          title="Bugs and feature requests"
          description="GitHub issues are the fastest route for anything about the code."
          to="https://github.com/bgalmes/rubit-mcp-mail/issues"
          target="_blank"
          variant="subtle"
        />
        <UPageCard
          icon="i-lucide-shield-check"
          title="Security disclosures"
          description="Pick the security topic above. Please don't file a public issue first."
          to="/security"
          variant="subtle"
        />
      </div>
    </div>
  </UContainer>
</template>
