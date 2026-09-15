<script setup lang="ts">
import type { Platform } from '~/composables/useReleases'

const props = withDefaults(defineProps<{ size?: 'md' | 'lg' | 'xl' }>(), { size: 'xl' })

const { recommended, latestFor, hasStable } = useReleases()
const os = useDetectedOs()

const PLATFORM_LABEL: Record<Platform, string> = { linux: 'Linux', windows: 'Windows' }

/**
 * Which release actually has a build for this visitor.
 *
 * `recommended` is the newest release that shipped anything, but a given
 * platform may not be in it - v1.0.0-rc.2's Windows build failed - so fall back
 * to the newest release that does carry one, and say so when they differ.
 */
const target = computed(() => {
  if (os.value !== 'linux' && os.value !== 'windows') return null
  const platform = os.value as Platform
  const release = recommended?.assets[platform] ? recommended : latestFor(platform)
  const asset = release?.assets[platform]
  return release && asset ? { release, asset, platform } : null
})

const olderThanRecommended = computed(
  () => Boolean(target.value && recommended && target.value.release.tag !== recommended.tag),
)
</script>

<template>
  <div class="flex flex-col items-center gap-3">
    <!-- Server-rendered and pre-detection: a neutral link that always works.
         ClientOnly keeps the OS-specific label out of the prerendered HTML so
         hydration can never mismatch. -->
    <ClientOnly>
      <template #fallback>
        <UButton to="/docs/install/installer" :size="props.size" icon="i-lucide-download" trailing-icon="i-lucide-arrow-right">
          Download the installer
        </UButton>
      </template>

      <UButton
        v-if="target"
        :to="target.asset.url"
        external
        :size="props.size"
        icon="i-lucide-download"
        class="font-medium"
      >
        Download for {{ PLATFORM_LABEL[target.platform] }}
      </UButton>

      <!-- No macOS installer has ever been built. Say so plainly rather than
           offering a download that does not exist. -->
      <UButton
        v-else-if="os === 'macos'"
        to="/docs/install/from-source"
        :size="props.size"
        color="neutral"
        variant="subtle"
        icon="i-simple-icons-apple"
        trailing-icon="i-lucide-arrow-right"
      >
        On macOS, run it from source
      </UButton>

      <UButton
        v-else
        to="/docs/install/installer"
        :size="props.size"
        icon="i-lucide-download"
        trailing-icon="i-lucide-arrow-right"
      >
        Download the installer
      </UButton>
    </ClientOnly>

    <ClientOnly>
      <div class="flex flex-col items-center gap-1.5 text-sm text-muted">
        <p v-if="target" class="flex flex-wrap items-center justify-center gap-x-2 gap-y-1">
          <span class="font-mono text-xs">{{ target.release.tag }}</span>
          <span aria-hidden="true">&middot;</span>
          <span>{{ target.asset.sizeLabel }}</span>
          <UBadge
            v-if="target.release.prerelease"
            color="warning"
            variant="subtle"
            size="sm"
            label="Pre-release"
          />
        </p>

        <p v-if="olderThanRecommended" class="text-xs text-warning max-w-sm text-center">
          {{ recommended?.tag }} has no {{ PLATFORM_LABEL[target!.platform] }} installer —
          this is {{ target!.release.tag }}, the newest {{ PLATFORM_LABEL[target!.platform] }} build.
        </p>

        <p v-else-if="target && !hasStable" class="text-xs max-w-sm text-center">
          There's no stable release yet. Release candidates are built and tested the same way.
        </p>

        <p v-if="os === 'macos'" class="text-xs max-w-sm text-center">
          rubit-mcp-mail ships Linux and Windows installers. On a Mac it's one
          <code class="font-mono">pip install -e .</code>
        </p>
      </div>
    </ClientOnly>

    <NuxtLink to="/changelog" class="text-xs text-muted hover:text-default transition-colors">
      All versions and checksums &rarr;
    </NuxtLink>
  </div>
</template>
