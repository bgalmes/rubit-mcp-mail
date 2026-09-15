/**
 * Renders public/og-cover.png, the social card the site unfurls with.
 *
 * Deliberately one static card rather than nuxt-og-image's per-page rendering:
 * that needs a native renderer (@resvg/resvg-js or @takumi-rs/core) which is an
 * optional peer nobody installs by default, and it has a history of mangling
 * asset paths under a non-root base URL. A native binary in CI is a lot to pay
 * for a social preview.
 *
 * Run by hand; the PNG is committed.
 *   node scripts/make-og-image.mjs
 */
import sharp from 'sharp'

const BG = '#0b0c0f'
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="brand" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3581FD"/><stop offset="1" stop-color="#0B5CD5"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#0B5CD5" stop-opacity="0"/>
      <stop offset="0.5" stop-color="#589DFF"/>
      <stop offset="1" stop-color="#0B5CD5" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="aurora" cx="0.25" cy="0" r="0.75">
      <stop offset="0" stop-color="#0B5CD5" stop-opacity="0.55"/>
      <stop offset="1" stop-color="#0B5CD5" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <rect width="1200" height="630" fill="${BG}"/>
  <rect width="1200" height="630" fill="url(#aurora)"/>
  <g stroke="#ffffff" stroke-opacity="0.045" stroke-width="1">
    ${Array.from({ length: 21 }, (_, i) => `<line x1="${i * 60}" y1="0" x2="${i * 60}" y2="630"/>`).join('')}
    ${Array.from({ length: 11 }, (_, i) => `<line x1="0" y1="${i * 60}" x2="1200" y2="${i * 60}"/>`).join('')}
  </g>
  <rect x="0" y="0" width="1200" height="2" fill="url(#bar)"/>

  <g transform="translate(80, 74)">
    <rect width="58" height="58" rx="16" fill="url(#brand)"/>
    <rect x="13" y="19" width="32" height="21" rx="2.5" fill="#fff"/>
    <path d="M14 20.5 29 31l15-10.5" fill="none" stroke="url(#brand)" stroke-width="2.9"
          stroke-linecap="round" stroke-linejoin="round"/>
    <text x="78" y="39" font-family="DejaVu Sans, Helvetica, Arial, sans-serif"
          font-size="30" font-weight="600" fill="#a1a1aa">rubit<tspan fill="#e4e4e7">-mcp-mail</tspan></text>
  </g>

  <text x="80" y="332" font-family="DejaVu Sans, Helvetica, Arial, sans-serif"
        font-size="68" font-weight="700" fill="#fafafa">Let Claude read your mail.</text>
  <text x="80" y="414" font-family="DejaVu Sans, Helvetica, Arial, sans-serif"
        font-size="68" font-weight="700" fill="#589DFF">Nothing else.</text>

  <text x="80" y="482" font-family="DejaVu Sans, Helvetica, Arial, sans-serif"
        font-size="29" fill="#a1a1aa">A read-only MCP server for IMAP. It never marks a message as read.</text>

  <text x="80" y="566" font-family="DejaVu Sans Mono, Courier New, monospace"
        font-size="23" fill="#71717a">bgalmes.github.io/rubit-mcp-mail</text>
  <text x="1120" y="566" text-anchor="end" font-family="DejaVu Sans, Helvetica, Arial, sans-serif"
        font-size="23" fill="#589DFF">Read-only by construction</text>
</svg>`

await sharp(Buffer.from(svg)).png({ compressionLevel: 9 }).toFile('public/og-cover.png')
console.log('  public/og-cover.png  1200x630')
