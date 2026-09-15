import payload from '~/data/releases.json'

export type Platform = 'linux' | 'windows'

export interface ReleaseAsset {
  name: string
  url: string
  size: number
  sizeLabel: string
  downloadCount: number
  sha256: string | null
}

export interface Release {
  tag: string
  version: string
  name: string
  prerelease: boolean
  publishedAt: string
  url: string
  body: string
  assets: Partial<Record<Platform, ReleaseAsset>>
}

export interface ReleaseIndex {
  generatedAt: string
  repo: string
  releases: Release[]
  platforms: Platform[]
  latest: string | null
  latestStable: string | null
  latestPrerelease: string | null
  recommended: string | null
  latestFor: Record<Platform, string | null>
}

const index = payload as unknown as ReleaseIndex

/**
 * Release data baked in at build time by scripts/fetch-releases.mjs.
 *
 * Three facts about this repo's real history shape every consumer:
 *   - every release so far is a prerelease, so `latestStable` is null
 *   - assets are not guaranteed: v1.0.0-rc.1 published none, v1.0.0-rc.2 had no
 *     Windows build, so `latestFor` can point at an older tag than `recommended`
 *   - there is no macOS installer, and `platforms` never contains one
 */
export function useReleases() {
  const byTag = (tag: string | null) => index.releases.find(r => r.tag === tag) ?? null

  return {
    all: index.releases,
    repo: index.repo,
    generatedAt: index.generatedAt,
    platforms: index.platforms,

    /** Newest stable that shipped an installer, else the newest prerelease that did. */
    recommended: byTag(index.recommended),
    latestStable: byTag(index.latestStable),
    latestPrerelease: byTag(index.latestPrerelease),
    hasStable: index.latestStable !== null,

    /** Newest release that actually carries an installer for this platform. */
    latestFor: (platform: Platform) => byTag(index.latestFor[platform]),

    releasesUrl: `https://github.com/${index.repo}/releases`,
  }
}
