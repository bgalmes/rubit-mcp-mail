/**
 * Drops the phantom base-path route from the sitemap.
 *
 * nitro's `crawlLinks` reads rendered hrefs, which already carry app.baseURL,
 * and records them as routes. For most pages it strips the base again, but the
 * bare `NuxtLink to="/"` in TheHeader renders as `/rubit-mcp-mail/` and survives
 * as a route in its own right, so @nuxtjs/sitemap publishes
 * https://bgalmes.github.io/rubit-mcp-mail/rubit-mcp-mail/ - a hard 404 handed
 * straight to crawlers.
 *
 * This cannot be done with `sitemap.exclude`: that filter runs the path through
 * `withoutBase()` first, which turns this entry into '/' and makes it
 * indistinguishable from the homepage. And it cannot be done with
 * `prerender.ignore`, because those same base-prefixed hrefs are how crawlLinks
 * discovers all 16 docs pages - ignoring the prefix silently drops them from
 * the build. The resolved URL set is the one place the entry is still
 * recognisable.
 */
export default defineNitroPlugin((nitroApp) => {
  const base = useRuntimeConfig().app.baseURL
  const basePath = base.replace(/\/+$/, '')
  if (!basePath) return

  nitroApp.hooks.hook('sitemap:resolved', (ctx: { urls: { loc: string }[] }) => {
    ctx.urls = ctx.urls.filter((entry) => {
      const bare = entry.loc.replace(/^https?:\/\/[^/]+/, '').replace(/\/+$/, '')
      // Match ONLY the doubled prefix. The hook sees fully-qualified locs, so a
      // bare `=== basePath` test here would also drop the homepage, which is
      // legitimately https://bgalmes.github.io/rubit-mcp-mail/.
      return !bare.startsWith(basePath + basePath)
    })
  })
})
