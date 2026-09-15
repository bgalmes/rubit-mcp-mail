<script setup lang="ts">
import type { ContentNavigationItem } from '@nuxt/content'

const navigation = inject<Ref<ContentNavigationItem[]>>('docs-navigation')

const links = [
  { label: 'Docs', to: '/docs', icon: 'i-lucide-book-open' },
  { label: 'Changelog', to: '/changelog', icon: 'i-lucide-history' },
  { label: 'Security', to: '/security', icon: 'i-lucide-shield-check' },
  { label: 'Contact', to: '/contact', icon: 'i-lucide-mail' },
]
</script>

<template>
  <UHeader :ui="{ root: 'border-b border-default/60 backdrop-blur-xl bg-default/70' }">
    <template #title>
      <NuxtLink to="/" class="focus-visible:outline-primary" aria-label="rubit-mcp-mail home">
        <BrandWordmark />
      </NuxtLink>
    </template>

    <UNavigationMenu :items="links" variant="link" />

    <template #right>
      <UContentSearchButton :collapsed="false" class="hidden sm:flex w-44" />
      <UContentSearchButton class="sm:hidden" />
      <UColorModeButton />
      <UButton
        to="https://github.com/bgalmes/rubit-mcp-mail"
        target="_blank"
        rel="noopener"
        icon="i-simple-icons-github"
        color="neutral"
        variant="ghost"
        aria-label="rubit-mcp-mail on GitHub"
      />
    </template>

    <!-- Mobile drawer: the same top-level links, then the full docs tree. -->
    <template #body>
      <UNavigationMenu :items="links" orientation="vertical" class="-mx-2.5" />
      <USeparator class="my-4" />
      <UContentNavigation :navigation="navigation" highlight />
    </template>
  </UHeader>
</template>
