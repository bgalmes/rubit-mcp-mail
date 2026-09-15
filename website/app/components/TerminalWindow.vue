<script setup lang="ts">
withDefaults(defineProps<{ title?: string }>(), { title: 'zsh' })
</script>

<template>
  <div class="overflow-hidden rounded-xl border border-default/70 bg-[color-mix(in_oklab,var(--ui-bg-elevated)_70%,transparent)] shadow-2xl shadow-black/30 backdrop-blur-md">
    <div class="flex items-center gap-2 border-b border-default/60 px-4 py-2.5">
      <span class="size-2.5 rounded-full bg-red-500/70" />
      <span class="size-2.5 rounded-full bg-amber-500/70" />
      <span class="size-2.5 rounded-full bg-emerald-500/70" />
      <span class="ml-2 font-mono text-xs text-muted">{{ title }}</span>
    </div>
    <div class="overflow-x-auto px-4 py-4">
      <pre class="font-mono text-[13px] leading-relaxed"><slot /></pre>
    </div>
  </div>
</template>
