/** Web3Forms' shared free-plan site key. Their own docs publish this value. */
const SITEKEY = '50b2fe65-b00b-4b9e-ad62-3ba471098be2'
const SRC = 'https://js.hcaptcha.com/1/api.js?render=explicit&onload=__hcaptchaReady'

declare global {
  interface Window {
    hcaptcha?: {
      render: (el: HTMLElement, opts: Record<string, unknown>) => string
      getResponse: (id: string) => string
      reset: (id: string) => void
      remove?: (id: string) => void
    }
    __hcaptchaReady?: () => void
  }
}

let scriptPromise: Promise<void> | null = null

function loadScript(): Promise<void> {
  if (import.meta.server) return Promise.resolve()
  if (window.hcaptcha) return Promise.resolve()
  scriptPromise ??= new Promise<void>((resolve, reject) => {
    window.__hcaptchaReady = () => resolve()
    const el = document.createElement('script')
    el.src = SRC
    el.async = true
    el.defer = true
    el.onerror = () => reject(new Error('hCaptcha failed to load'))
    document.head.appendChild(el)
  })
  return scriptPromise
}

/**
 * Renders hCaptcha explicitly into `container`.
 *
 * Deliberately not Web3Forms' own client/script.js: that scans the DOM once on
 * load for `.h-captcha[data-captcha]`, which in a Nuxt SPA happens before a
 * client-side navigation to /contact ever mounts the form. The widget would
 * silently never appear and the form could not be submitted.
 */
export function useHCaptcha(container: Ref<HTMLElement | null>) {
  const widgetId = ref<string | null>(null)
  const ready = ref(false)
  const failed = ref(false)
  const colorMode = useColorMode()

  onMounted(async () => {
    try {
      await loadScript()
      if (!container.value || !window.hcaptcha) return
      widgetId.value = window.hcaptcha.render(container.value, {
        sitekey: SITEKEY,
        theme: colorMode.value === 'dark' ? 'dark' : 'light',
      })
      ready.value = true
    } catch {
      failed.value = true
    }
  })

  onBeforeUnmount(() => {
    if (widgetId.value !== null) window.hcaptcha?.reset(widgetId.value)
  })

  return {
    ready,
    failed,
    token: () => (widgetId.value === null ? '' : (window.hcaptcha?.getResponse(widgetId.value) ?? '')),
    reset: () => {
      if (widgetId.value !== null) window.hcaptcha?.reset(widgetId.value)
    },
  }
}
