<script setup lang="ts">
import { formatDate, tagToAnchor } from '~/utils/format'

const { all, recommended, hasStable, releasesUrl, generatedAt } = useReleases()

useSeoMeta({
  title: 'Changelog',
  description:
    'Every release of rubit-mcp-mail, what changed in it, and the installers it shipped — '
    + 'with sizes and SHA-256 checksums, including older versions.',
})

// All three releases so far are prereleases, so defaulting this to false would
// show an empty page. It flips to a real filter the moment a stable ships.
const showPrereleases = ref(true)
const hasAnyStable = computed(() => all.some(r => !r.prerelease))

const visible = computed(() =>
  showPrereleases.value ? all : all.filter(r => !r.prerelease),
)

// Deep links like /changelog#v1-0-0-rc-3 come from the download button and the
// GitHub release notes, so honour them after the list renders.
onMounted(async () => {
  const hash = useRoute().hash
  if (!hash) return
  await nextTick()
  document.querySelector(hash)?.scrollIntoView({ behavior: 'smooth' })
})
</script>

<template>
  <UContainer class="py-16 sm:py-24">
    <div class="mx-auto max-w-3xl">
      <UPageHeader
        title="Changelog"
        description="Every release, what changed in it, and the installers it shipped. Older versions stay downloadable."
      >
        <template #links>
          <UButton
            :to="releasesUrl"
            target="_blank"
            rel="noopener"
            color="neutral"
            variant="subtle"
            icon="i-simple-icons-github"
            label="On GitHub"
          />
        </template>
      </UPageHeader>

      <UAlert
        v-if="!hasStable"
        class="mt-8"
        color="warning"
        variant="subtle"
        icon="i-lucide-flask-conical"
        title="No stable release yet"
        :description="`Everything published so far is a release candidate. ${recommended?.tag ?? ''} is the newest, and it's built and tested exactly like a stable release would be.`"
      />

      <div v-if="hasAnyStable" class="mt-8 flex items-center gap-2">
        <USwitch v-model="showPrereleases" label="Show pre-releases" />
      </div>

      <div v-if="!visible.length" class="mt-12">
        <UAlert
          color="neutral"
          variant="subtle"
          icon="i-lucide-inbox"
          title="Nothing to show"
          description="No releases match this filter."
        />
      </div>

      <ol v-else class="mt-12 space-y-14">
        <li
          v-for="release in visible"
          :id="tagToAnchor(release.tag)"
          :key="release.tag"
          class="scroll-mt-24"
        >
          <div class="flex flex-wrap items-center gap-3">
            <h2 class="font-mono text-xl font-semibold text-highlighted">
              {{ release.tag }}
            </h2>
            <UBadge
              v-if="release.prerelease"
              color="warning"
              variant="subtle"
              size="sm"
              label="Pre-release"
            />
            <UBadge
              v-if="recommended && release.tag === recommended.tag"
              color="primary"
              variant="subtle"
              size="sm"
              label="Recommended"
            />
            <time :datetime="release.publishedAt" class="ml-auto text-sm text-muted">
              {{ formatDate(release.publishedAt) }}
            </time>
          </div>

          <!-- The GitHub release body is byte-identical to the matching
               CHANGELOG.md section, so it renders through the same prose
               components as the docs. Shapes vary: rc.1 is a bare list with no
               heading at all. -->
          <div v-if="release.body" class="mt-5">
            <MDC :value="release.body" class="prose-sm" />
          </div>
          <p v-else class="mt-5 text-sm text-muted italic">
            No release notes were published for this version.
          </p>

          <div class="mt-6 rounded-xl border border-default/70 bg-elevated/30 p-5">
            <h3 class="mb-4 flex items-center gap-2 text-sm font-semibold text-highlighted">
              <UIcon name="i-lucide-download" class="size-4 text-primary" />
              Installers
            </h3>
            <DownloadTable :release="release" />
          </div>

          <div class="mt-4">
            <UButton
              :to="release.url"
              target="_blank"
              rel="noopener"
              color="neutral"
              variant="link"
              size="xs"
              trailing-icon="i-lucide-external-link"
              label="View this release on GitHub"
              class="px-0"
            />
          </div>
        </li>
      </ol>

      <div class="mt-16 rounded-xl border border-default/60 bg-elevated/20 p-5 text-sm text-muted">
        <p class="flex items-start gap-2">
          <UIcon name="i-lucide-shield-check" class="mt-0.5 size-4 shrink-0 text-primary" />
          <span>
            Every installer is unsigned, so Windows Defender and Avast may flag it —
            a <NuxtLink to="/docs/install/installer#a-note-on-antivirus-warnings" class="text-primary hover:underline">known false positive</NuxtLink>
            for PyInstaller binaries. Verify what you downloaded against the SHA-256 above:
            <code class="font-mono text-xs">sha256sum &lt;file&gt;</code> on Linux,
            <code class="font-mono text-xs">Get-FileHash &lt;file&gt;</code> on Windows.
          </span>
        </p>
        <p class="mt-3 text-xs">
          Release data baked in at build time
          <time :datetime="generatedAt">{{ formatDate(generatedAt) }}</time>.
        </p>
      </div>
    </div>
  </UContainer>
</template>
