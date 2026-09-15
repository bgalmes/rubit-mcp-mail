<script setup lang="ts">
// Unique per instance: two marks on one page would otherwise share a gradient id.
const gradientId = `brand-${useId()}`
</script>

<template>
  <svg viewBox="0 0 48 48" fill="none" aria-hidden="true" focusable="false">
    <rect width="48" height="48" rx="13" :fill="`url(#${gradientId})`" />
    <rect x="11" y="16" width="26" height="17" rx="2" fill="white" />
    <path
      d="M11.8 17.2 24 26l12.2-8.8"
      :stroke="`url(#${gradientId})`"
      stroke-width="2.4"
      stroke-linecap="round"
      stroke-linejoin="round"
      fill="none"
    />
    <defs>
      <linearGradient :id="gradientId" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
        <stop stop-color="#3581FD" />
        <stop offset="1" stop-color="#0B5CD5" />
      </linearGradient>
    </defs>
  </svg>
</template>
