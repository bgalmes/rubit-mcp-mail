/**
 * Bakes the GitHub Releases list into the site at build time.
 *
 * The site is statically generated onto GitHub Pages, so it has no server to
 * proxy api.github.com and no business asking every visitor's browser to do it
 * either - unauthenticated the API allows 60 requests per hour per IP, which a
 * public page cannot rely on. The data only changes when a release is cut, so
 * we fetch once here and `app/data/releases.json` ships inside the prerendered
 * HTML.
 *
 * Freshness is handled in CI: publish-release.yml calls deploy-website.yml
 * directly after the installers are attached. It cannot wait on a
 * `release: published` event, because a release created by GITHUB_TOKEN never
 * fires one - the same constraint the whole release chain is built around.
 *
 * This script must never fail the build. Offline, rate-limited or behind a
 * proxy it falls back to the previous file, and failing that to a valid empty
 * payload, so `npm run dev` still works on a plane.
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = 'bgalmes/rubit-mcp-mail'
const API = `https://api.github.com/repos/${REPO}/releases?per_page=100`
const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(HERE, '../app/data/releases.json')
/** Tracked seed. app/data/releases.json is gitignored, so on a fresh CI clone it
 *  is the only fallback that exists when the API is unreachable. */
const SEED = resolve(HERE, 'releases.fallback.json')

/** In CI. A site whose download button has nothing to point at is worse than a
 *  failed deploy, so --strict turns an empty result into a non-zero exit. */
const STRICT = process.argv.includes('--strict')

/** The only platforms that have ever been built. Deliberately no macOS. */
const PLATFORMS = ['linux', 'windows']

/** Installers are named `rubit-mcp-mail-setup-linux` / `-windows.exe`. */
function platformOf(assetName) {
  const n = assetName.toLowerCase()
  if (n.includes('linux')) return 'linux'
  if (n.includes('windows') || n.endsWith('.exe')) return 'windows'
  return null
}

/** The API returns `sha256:<hex>`; the bare hex is what users paste into a checksum tool. */
function sha256Of(asset) {
  const digest = asset.digest
  if (typeof digest !== 'string') return null
  return digest.startsWith('sha256:') ? digest.slice(7) : digest
}

function normalize(release) {
  const assets = {}
  for (const asset of release.assets ?? []) {
    const platform = platformOf(asset.name ?? '')
    if (!platform) continue
    const size = asset.size ?? 0
    assets[platform] = {
      name: asset.name,
      url: asset.browser_download_url,
      size,
      // Computed once here so no two components disagree on MB vs MiB.
      sizeLabel: size ? `${(size / 1024 / 1024).toFixed(1)} MB` : '',
      downloadCount: asset.download_count ?? 0,
      sha256: sha256Of(asset),
    }
  }
  return {
    tag: release.tag_name,
    version: String(release.tag_name ?? '').replace(/^v/, ''),
    name: release.name || release.tag_name,
    prerelease: Boolean(release.prerelease),
    publishedAt: release.published_at,
    url: release.html_url,
    body: (release.body ?? '').trim(),
    assets,
  }
}

function payload(releases) {
  const sorted = [...releases].sort(
    (a, b) => Date.parse(b.publishedAt ?? 0) - Date.parse(a.publishedAt ?? 0),
  )

  // "Latest" is only useful if it actually shipped something: v1.0.0-rc.1
  // published no installers at all, so it must never be offered as a download.
  const shipped = sorted.filter((r) => Object.keys(r.assets).length > 0)
  const latestStable = shipped.find((r) => !r.prerelease) ?? null
  const latestPrerelease = shipped.find((r) => r.prerelease) ?? null

  // Per-platform walk-back. v1.0.0-rc.2's Windows build failed, so the newest
  // release carrying a Windows installer is not always the newest release.
  const latestFor = {}
  for (const platform of PLATFORMS) {
    latestFor[platform] = sorted.find((r) => r.assets[platform])?.tag ?? null
  }

  return {
    generatedAt: new Date().toISOString(),
    repo: REPO,
    releases: sorted,
    platforms: PLATFORMS,
    latest: sorted[0]?.tag ?? null,
    // Every release so far is a prerelease, so `latestStable` is legitimately
    // null and the download UI has to fall back and say so.
    latestStable: latestStable?.tag ?? null,
    latestPrerelease: latestPrerelease?.tag ?? null,
    recommended: (latestStable ?? latestPrerelease)?.tag ?? null,
    latestFor,
  }
}

async function fetchReleases() {
  const headers = {
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'rubit-mcp-mail-website-build',
  }
  // Raises the rate limit from 60/hr to 5000/hr when CI provides one.
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(API, { headers, signal: AbortSignal.timeout(20_000) })
  if (!res.ok) throw new Error(`GitHub API responded ${res.status} ${res.statusText}`)

  const json = await res.json()
  if (!Array.isArray(json)) throw new Error('GitHub API did not return an array')
  return json.filter((r) => !r.draft).map(normalize)
}

async function readPayload(path) {
  try {
    const existing = JSON.parse(await readFile(path, 'utf8'))
    if (Array.isArray(existing?.releases) && existing.releases.length) return existing
  } catch {
    /* not usable */
  }
  return null
}

async function main() {
  let data
  try {
    data = payload(await fetchReleases())
    console.log(`[releases] fetched ${data.releases.length} release(s) from ${REPO}`)
  } catch (error) {
    console.warn(`[releases] fetch failed: ${error.message}`)
    const stale = (await readPayload(OUT)) ?? (await readPayload(SEED))
    if (stale) {
      console.warn('[releases] falling back to the last known good release list')
      data = stale
    } else {
      console.warn('[releases] no fallback available; writing an empty payload')
      data = payload([])
    }
  }

  if (STRICT) {
    const withAssets = data.releases.filter((r) => Object.keys(r.assets).length > 0)
    if (!withAssets.length) {
      console.error(
        '[releases] --strict: no release carries an installer. Refusing to build a ' +
          'site whose download button has nothing to point at.',
      )
      process.exit(1)
    }
  }

  await mkdir(dirname(OUT), { recursive: true })
  await writeFile(OUT, `${JSON.stringify(data, null, 2)}\n`, 'utf8')
  console.log(`[releases] wrote ${OUT}`)
}

await main()
