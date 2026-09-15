<template>
  <!-- Purely decorative: no canvas, no JS, no images, nothing to hydrate.
       Four CSS layers - grid, two drifting blobs, a beam and film grain.
       All of it freezes under prefers-reduced-motion. -->
  <div class="backdrop" aria-hidden="true">
    <div class="backdrop-grid" />
    <div class="backdrop-aurora backdrop-aurora-a" />
    <div class="backdrop-aurora backdrop-aurora-b" />
    <div class="backdrop-beam" />
    <div class="backdrop-noise" />
  </div>
</template>
