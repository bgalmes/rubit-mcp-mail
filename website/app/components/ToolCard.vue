<script setup lang="ts">
defineProps<{
  name: string
  icon: string
  summary: string
  detail: string
}>()
</script>

<template>
  <div class="group relative flex flex-col gap-3 rounded-xl border border-default/70 bg-elevated/40 p-5 backdrop-blur-sm transition-colors hover:border-primary/40">
    <div class="flex items-center gap-2.5">
      <UIcon :name="icon" class="size-4 shrink-0 text-primary" />
      <code class="font-mono text-sm text-highlighted">{{ name }}</code>
      <UBadge
        color="neutral"
        variant="subtle"
        size="sm"
        class="ml-auto"
        icon="i-lucide-eye"
        label="read"
      />
    </div>
    <p class="text-sm text-default">{{ summary }}</p>
    <p class="text-xs text-muted">{{ detail }}</p>
  </div>
</template>
