<script setup lang="ts">
import type { Platform, Release } from '~/composables/useReleases'

const props = defineProps<{ release: Release }>()

const PLATFORM_LABEL: Record<Platform, string> = { linux: 'Linux', windows: 'Windows' }
const PLATFORM_ICON: Record<Platform, string> = {
  linux: 'i-simple-icons-linux',
  windows: 'i-simple-icons-windows',
}

const { platforms } = useReleases()
const toast = useToast()

const rows = computed(() =>
  platforms.map(platform => ({ platform, asset: props.release.assets[platform] ?? null })),
)

const anyAsset = computed(() => rows.value.some(r => r.asset))

async function copy(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.add({ title: `${what} copied`, color: 'success', icon: 'i-lucide-check' })
  } catch {
    toast.add({ title: 'Could not copy', color: 'error', icon: 'i-lucide-x' })
  }
}
</script>

<template>
  <!-- v1.0.0-rc.1 shipped no installers at all; say so rather than showing an
       empty table or, worse, a dead link. -->
  <p v-if="!anyAsset" class="text-sm text-muted italic">
    No installers were attached to this release.
  </p>

  <div v-else class="overflow-x-auto">
    <table class="w-full min-w-[34rem] text-sm">
      <thead>
        <tr class="border-b border-default/60 text-left text-xs uppercase tracking-wide text-muted">
          <th class="py-2 pr-4 font-medium">Platform</th>
          <th class="py-2 pr-4 font-medium">File</th>
          <th class="py-2 pr-4 font-medium">Size</th>
          <th class="py-2 pr-4 font-medium">SHA-256</th>
          <th class="py-2 font-medium sr-only">Download</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.platform" class="border-b border-default/40 last:border-0">
          <td class="py-3 pr-4 whitespace-nowrap">
            <span class="inline-flex items-center gap-2">
              <UIcon :name="PLATFORM_ICON[row.platform]" class="size-4 text-muted" />
              {{ PLATFORM_LABEL[row.platform] }}
            </span>
          </td>

          <template v-if="row.asset">
            <td class="py-3 pr-4 font-mono text-xs break-all">{{ row.asset.name }}</td>
            <td class="py-3 pr-4 whitespace-nowrap text-muted">{{ row.asset.sizeLabel }}</td>
            <td class="py-3 pr-4">
              <UButton
                v-if="row.asset.sha256"
                color="neutral"
                variant="ghost"
                size="xs"
                icon="i-lucide-copy"
                class="font-mono"
                :label="`${row.asset.sha256.slice(0, 10)}…`"
                :aria-label="`Copy the SHA-256 for ${row.asset.name}`"
                @click="copy(row.asset.sha256, 'SHA-256')"
              />
              <span v-else class="text-muted">—</span>
            </td>
            <td class="py-3 text-right whitespace-nowrap">
              <UButton
                :to="row.asset.url"
                external
                size="xs"
                icon="i-lucide-download"
                :label="`Download`"
                :aria-label="`Download ${row.asset.name}`"
              />
            </td>
          </template>

          <!-- v1.0.0-rc.2's Windows build failed. A greyed-out reason beats a
               missing row, which just looks like the page is broken. -->
          <td v-else colspan="4" class="py-3 text-muted italic">
            Not published for this version
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
