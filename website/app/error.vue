<script setup lang="ts">
// Also what a GitHub Pages 404 resolves to. The nitro static preset writes its
// own SPA fallback to 404.html and overwrites anything a page emits at that
// route, so the shell boots, no route matches, and this renders. A page at
// /404.html was tried and silently clobbered - don't add one back.
import type { NuxtError } from '#app'

const props = defineProps<{ error: NuxtError }>()

// Deliberately not usePageSeo(): an error page must not claim a canonical URL,
// and it should never be indexed. It also bypasses app.vue, so without an
// explicit description here 404.html ships with no SEO meta at all.
useSeoMeta({
  title: props.error.statusCode === 404 ? 'Page not found' : 'Something went wrong',
  description: 'That page does not exist on the rubit-mcp-mail documentation site.',
  robots: 'noindex, follow',
})
</script>

<template>
  <UApp>
    <TheHeader />
    <UMain>
      <NotFound :status-code="error.statusCode" />
    </UMain>
    <TheFooter />
  </UApp>
</template>
