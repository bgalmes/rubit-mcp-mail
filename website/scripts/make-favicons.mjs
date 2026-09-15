/**
 * Rasterizes public/favicon.svg into the PNG and ICO sizes browsers ask for.
 *
 * Run by hand after editing the SVG - the outputs are committed, so the build
 * never depends on a rasterizer being installed:
 *
 *   node scripts/make-favicons.mjs
 *
 * sharp comes in with @nuxt/image, so there is no extra dependency.
 */
import sharp from 'sharp'
import { readFile, writeFile } from 'node:fs/promises'

const SRC = 'public/favicon.svg'
const svg = await readFile(SRC)

// iOS masks its own corners onto an opaque square, so a rounded, transparent
// source leaves grey wedges. Square the corners just for that one file.
const appleSvg = Buffer.from((await readFile(SRC, 'utf8')).replace('rx="13"', 'rx="0"'))

for (const [out, src, size] of [
  ['public/favicon-32.png', svg, 32],
  ['public/icon-192.png', svg, 192],
  ['public/icon-512.png', svg, 512],
  ['public/apple-touch-icon.png', appleSvg, 180],
]) {
  await sharp(src, { density: 384 }).resize(size, size).png({ compressionLevel: 9 }).toFile(out)
  console.log(`  ${out}  ${size}x${size}`)
}

// A minimal .ico wrapping one 32x32 PNG - the PNG-in-ICO form every browser
// since IE11 understands. Saves pulling in an ICO encoder for one file.
const png = await sharp(svg, { density: 384 }).resize(32, 32).png({ compressionLevel: 9 }).toBuffer()
const header = Buffer.alloc(6)
header.writeUInt16LE(1, 2) // type: icon
header.writeUInt16LE(1, 4) // image count
const entry = Buffer.alloc(16)
entry[0] = 32 // width
entry[1] = 32 // height
entry.writeUInt16LE(1, 4) // colour planes
entry.writeUInt16LE(32, 6) // bits per pixel
entry.writeUInt32LE(png.length, 8)
entry.writeUInt32LE(22, 12) // offset: 6-byte header + 16-byte entry
await writeFile('public/favicon.ico', Buffer.concat([header, entry, png]))
console.log(`  public/favicon.ico  32x32`)
