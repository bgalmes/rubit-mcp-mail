import { joinURL } from 'ufo'

/**
 * Prefixes a `public/` path with the app's base URL.
 *
 * NuxtLink, <NuxtImg> and bundled assets handle `app.baseURL` themselves, but
 * raw strings in useHead/useSeoMeta do not - a plain `/favicon.svg` resolves to
 * https://bgalmes.github.io/favicon.svg on GitHub Pages, not
 * https://bgalmes.github.io/rubit-mcp-mail/favicon.svg. Route every hand-written
 * public path through here.
 */
export function useAssetUrl() {
  const base = useRuntimeConfig().app.baseURL
  return (path: string) => joinURL(base, path)
}
