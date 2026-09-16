import { joinURL, withTrailingSlash } from 'ufo'

interface PageSeo {
  title: string
  description: string
  /** Passed straight through to useSeoMeta, e.g. 'noindex, follow'. */
  robots?: string
}

/**
 * useSeoMeta, plus the tags Nuxt does not mirror for you.
 *
 * `useSeoMeta({ title, description })` sets only <title> and
 * <meta name="description">. It does NOT populate og:title, og:description,
 * twitter:title or twitter:description, so a link shared in Slack or Discord
 * unfurls with the cover image and no text at all. It also emits no canonical.
 *
 * nuxt-seo-utils would add all of this, but it arrives with @nuxtjs/sitemap
 * (already registered - see the module note in nuxt.config.ts) and
 * nuxt-og-image, which would duplicate the hand-built og-cover.png from
 * scripts/make-og-image.mjs. This is the small version.
 *
 * Absolute URLs are composed exactly the way app.vue builds ogImage: site.url
 * carries the origin and app.baseURL the sub-path, because GitHub Pages serves
 * this repo from /rubit-mcp-mail/.
 *
 * The trailing slash is load-bearing. GitHub Pages 301s every extensionless URL
 * to its slashed form (/security -> /security/), so the unslashed spelling is
 * never the URL a crawler ends up on. Pointing a canonical - or a sitemap entry,
 * hence site.trailingSlash in nuxt.config.ts - at a redirect is a wasted hop.
 */
export function usePageSeo(meta: PageSeo) {
  const site = useSiteConfig()
  const route = useRoute()
  const base = useRuntimeConfig().app.baseURL

  const canonical = withTrailingSlash(
    joinURL(site.url?.toString() ?? '', base, route.path),
  )

  useSeoMeta({
    title: meta.title,
    description: meta.description,
    ...(meta.robots ? { robots: meta.robots } : {}),
    ogTitle: meta.title,
    ogDescription: meta.description,
    ogUrl: canonical,
    twitterTitle: meta.title,
    twitterDescription: meta.description,
  })

  useHead({ link: [{ rel: 'canonical', href: canonical }] })

  return { canonical }
}
