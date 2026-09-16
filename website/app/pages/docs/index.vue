<script setup lang="ts">
// /docs itself is content: content/docs/1.index.md renders at this path. The
// catch-all sibling does not match an empty slug, so this thin page delegates.
definePageMeta({ layout: 'docs' })

const { data: page } = await useAsyncData('docs-index', () =>
  queryCollection('docs').path('/docs').first(),
)

if (!page.value) {
  throw createError({ statusCode: 404, statusMessage: 'Docs home not found', fatal: true })
}

usePageSeo({ title: page.value.title, description: page.value.description })
</script>

<template>
  <UPage v-if="page">
    <UPageHeader :title="page.title" :description="page.description" />
    <UPageBody>
      <ContentRenderer :value="page" />
    </UPageBody>
    <template v-if="page.body?.toc?.links?.length" #right>
      <UContentToc title="On this page" :links="page.body.toc.links" />
    </template>
  </UPage>
</template>
