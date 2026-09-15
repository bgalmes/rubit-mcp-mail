/**
 * Serves .output/public under /rubit-mcp-mail/, the way GitHub Pages will.
 *
 * Serving it at / proves nothing: the whole class of base-URL bugs (a favicon
 * that 404s, a content database fetched from the wrong path) only shows up when
 * the site is mounted on a sub-path.
 */
import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize, resolve } from 'node:path'

const ROOT = resolve(import.meta.dirname, '../.output/public')
const BASE = process.env.NUXT_APP_BASE_URL || '/rubit-mcp-mail/'
const PORT = Number(process.env.PORT || 4000)

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8',
  '.wasm': 'application/wasm',
}

if (!existsSync(ROOT)) {
  console.error(`No build at ${ROOT}. Run: npm run generate:gh`)
  process.exit(1)
}

createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost')

  if (!url.pathname.startsWith(BASE)) {
    res.writeHead(404, { 'content-type': 'text/plain' })
    return res.end(`Not found. The site is mounted at ${BASE}`)
  }

  const rel = normalize(url.pathname.slice(BASE.length)).replace(/^(\.\.[/\\])+/, '')
  let file = join(ROOT, rel)

  if (existsSync(file) && statSync(file).isDirectory()) file = join(file, 'index.html')
  if (!existsSync(file) && existsSync(`${file}.html`)) file = `${file}.html`
  if (!existsSync(file)) {
    res.writeHead(404, { 'content-type': TYPES['.html'] })
    return createReadStream(join(ROOT, '404.html')).pipe(res)
  }

  res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream' })
  createReadStream(file).pipe(res)
}).listen(PORT, () => {
  console.log(`Serving ${ROOT}\n  -> http://localhost:${PORT}${BASE}`)
})
