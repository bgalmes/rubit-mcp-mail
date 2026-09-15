<script setup lang="ts">
withDefaults(
  defineProps<{ statusCode?: number, message?: string }>(),
  { statusCode: 404, message: '' },
)
</script>

<template>
  <section class="relative isolate overflow-hidden">
    <AuroraBackdrop />
    <UContainer class="relative z-10 flex min-h-[60vh] flex-col items-center justify-center py-24 text-center">
      <p class="font-mono text-6xl font-semibold text-primary">{{ statusCode }}</p>
      <h1 class="mt-6 text-2xl font-semibold tracking-tight text-highlighted sm:text-3xl">
        {{ statusCode === 404 ? 'That page does not exist' : 'Something went wrong' }}
      </h1>
      <p class="mt-3 max-w-md text-muted">
        {{ message || (statusCode === 404
          ? 'The link may be out of date. The docs index is a good place to pick the thread back up.'
          : 'Try again, or open an issue if it keeps happening.') }}
      </p>
      <div class="mt-8 flex flex-wrap items-center justify-center gap-3">
        <UButton to="/" icon="i-lucide-home" label="Home" />
        <UButton to="/docs" color="neutral" variant="subtle" icon="i-lucide-book-open" label="Docs" />
        <UButton to="/changelog" color="neutral" variant="ghost" icon="i-lucide-history" label="Changelog" />
      </div>
    </UContainer>
  </section>
</template>
