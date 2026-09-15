<script setup lang="ts">
import { joinURL } from 'ufo'

const asset = useAssetUrl()
const site = useSiteConfig()

// Docs navigation and search index are fetched once here and shared with every
// page through provide/inject, so a client-side navigation never refetches them.
const { data: navigation } = await useAsyncData('docs-navigation', () =>
  queryCollectionNavigation('docs'),
)
provide('docs-navigation', navigation)

const { data: searchSections } = await useLazyAsyncData('docs-search', () =>
  queryCollectionSearchSections('docs'),
  { server: false },
)

useHead({
  titleTemplate: (title?: string) => (title ? `${title} · rubit-mcp-mail` : 'rubit-mcp-mail'),
  // Nuxt does not prefix app.baseURL onto raw head hrefs, so every one of these
  // goes through useAssetUrl(). A bare '/favicon.svg' 404s under /rubit-mcp-mail/.
  link: [
    { rel: 'icon', type: 'image/svg+xml', href: asset('/favicon.svg') },
    { rel: 'icon', type: 'image/png', sizes: '32x32', href: asset('/favicon-32.png') },
    { rel: 'apple-touch-icon', sizes: '180x180', href: asset('/apple-touch-icon.png') },
  ],
})

// OG images must be absolute, and on Pages the origin and the sub-path live in
// two different settings - site.url carries the origin, app.baseURL the path.
const ogImage = joinURL(site.url?.toString() ?? '', useRuntimeConfig().app.baseURL, 'og-cover.png')

useSeoMeta({
  ogSiteName: 'rubit-mcp-mail',
  ogType: 'website',
  twitterCard: 'summary_large_image',
  description: site.description,
  ogImage,
  twitterImage: ogImage,
})
</script>

<template>
  <UApp>
    <NuxtLoadingIndicator color="var(--ui-primary)" />
    <TheHeader />
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
    <TheFooter />

    <ClientOnly>
      <LazyUContentSearch :files="searchSections" :navigation="navigation" shortcut="meta_k" />
    </ClientOnly>
  </UApp>
</template>
