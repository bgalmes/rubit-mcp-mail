<script setup lang="ts">
// Also what a GitHub Pages 404 resolves to. The nitro static preset writes its
// own SPA fallback to 404.html and overwrites anything a page emits at that
// route, so the shell boots, no route matches, and this renders. A page at
// /404.html was tried and silently clobbered - don't add one back.
import type { NuxtError } from '#app'

const props = defineProps<{ error: NuxtError }>()

useHead({ title: props.error.statusCode === 404 ? 'Page not found' : 'Something went wrong' })
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
