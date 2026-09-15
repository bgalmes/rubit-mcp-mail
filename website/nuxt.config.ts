// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2026-09-15',
  devtools: { enabled: true },
  future: { compatibilityVersion: 4 },

  // ORDER MATTERS: '@nuxt/ui' must come before '@nuxt/content', or the prose
  // components fall back to unstyled defaults.
  //
  // @nuxt/fonts, @nuxt/icon, @nuxtjs/mdc and @nuxtjs/color-mode are deliberately
  // absent: @nuxt/ui auto-installs all four via its moduleDependencies hook, and
  // listing them here would register them twice.
  modules: ['@nuxt/image', '@nuxt/ui', '@nuxt/content', '@nuxtjs/sitemap'],

  css: ['~/assets/css/main.css'],

  app: {
    // '/' locally; the deploy workflow exports NUXT_APP_BASE_URL=/rubit-mcp-mail/
    // because GitHub Pages serves this repo from a sub-path.
    baseURL: process.env.NUXT_APP_BASE_URL || '/',
    head: {
      htmlAttrs: { lang: 'en' },
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'theme-color', content: '#0b0c0f' },
      ],
      // NOTE: favicons are NOT declared here. Nuxt does not prefix app.baseURL
      // onto raw head hrefs, so '/favicon.svg' would resolve to
      // bgalmes.github.io/favicon.svg and 404. app.vue sets them through
      // useAssetUrl() instead.
    },
  },

  site: {
    // Origin only. nuxt-site-config rejects a path here and composes absolute
    // URLs from this plus app.baseURL, so the sub-path belongs to baseURL alone.
    url: process.env.NUXT_PUBLIC_SITE_URL || 'https://bgalmes.github.io',
    name: 'rubit-mcp-mail',
    description:
      'A read-only MCP server that lets Claude read your mail over IMAP. Outlook, Gmail, '
      + 'Fastmail, iCloud or self-hosted - and it never marks a message as read.',
  },

  // Dark-first. @nuxt/ui already configures @nuxtjs/color-mode with
  // classSuffix: '' so Tailwind's `.dark` variant works - do not override that.
  colorMode: { preference: 'dark', fallback: 'dark' },

  ui: {
    // @nuxtjs/mdc is registered as optional unless this is true. The changelog
    // renders GitHub release notes through <MDC>, so it must be guaranteed.
    mdc: true,
  },

  icon: {
    // Inline the SVG rather than @nuxt/icon's default CSS-mask mode: the mask
    // rules are injected by a client plugin, so on a prerendered page every
    // icon is an empty span until JS runs. 'svg' puts real markup in the
    // static HTML instead.
    mode: 'svg',
    // Bundle @iconify-json/lucide and @iconify-json/simple-icons into the build.
    // Without this @nuxt/icon resolves every `i-lucide-*` through
    // api.iconify.design at runtime, in the visitor's browser.
    clientBundle: { scan: true, includeCustomCollections: true },
    provider: 'iconify',
    // Everything is bundled at build time, so there is nothing legitimate left
    // to fetch. Without this, an icon the scanner misses would silently be
    // pulled from api.iconify.design in the visitor's browser - a third-party
    // request on a site whose whole pitch is that it does not phone home. A
    // missing icon is the better failure.
    fallbackToApi: false,
  },

  content: {
    build: {
      markdown: {
        toc: { depth: 3, searchDepth: 2 },
        highlight: {
          // Only real shiki grammars belong here - an unknown id makes the
          // mdc-highlighter template fail to compile. 'text'/'plaintext' are
          // NOT grammars: shiki renders unlabelled fences as plain text itself.
          langs: [
            'bash', 'powershell', 'toml', 'json', 'jsonc', 'python',
            'ts', 'vue', 'yaml', 'ini', 'diff',
          ],
        },
      },
    },
    // Node 22.5+ ships node:sqlite, so there is nothing to compile.
    experimental: { sqliteConnector: 'native' },
  },

  sitemap: {
    autoLastmod: true,
    // Keeps the contact form (and its public Web3Forms key) out of search results.
    exclude: ['/contact'],
  },

  runtimeConfig: {
    public: {
      // Public by design: a Web3Forms access key can only ever deliver to the
      // one address it was created against, so shipping it in the bundle costs
      // nothing. Set NUXT_PUBLIC_WEB3FORMS_KEY locally (website/.env) and as the
      // WEB3FORMS_ACCESS_KEY repo secret. Empty is handled: the contact form
      // degrades to a "not configured yet" notice instead of breaking.
      web3formsKey: '',
    },
  },

  nitro: {
    // Driven from the environment so `nuxt dev` behaves like a normal site and
    // only CI (and `npm run generate:gh`) builds for Pages. The preset sets
    // output.publicDir, enables prerender.crawlLinks, prerenders / and
    // /404.html, and writes .nojekyll in its `compiled` hook.
    preset: process.env.NITRO_PRESET || undefined,
    prerender: {
      crawlLinks: true,
      routes: ['/', '/docs', '/changelog', '/contact', '/security'],
      // A dead internal link or an empty content query must fail the deploy
      // rather than ship a broken page.
      failOnError: true,
    },
  },
})
