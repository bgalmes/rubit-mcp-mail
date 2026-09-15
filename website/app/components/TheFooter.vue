<script setup lang="ts">
const year = new Date().getFullYear()
</script>

<template>
  <UFooter :ui="{ root: 'border-t border-default/60' }">
    <template #top>
      <UContainer>
        <UFooterColumns
          :columns="[
            {
              label: 'Product',
              children: [
                { label: 'Download', to: '/#download' },
                { label: 'Changelog', to: '/changelog' },
                { label: 'Security', to: '/security' },
              ],
            },
            {
              label: 'Documentation',
              children: [
                { label: 'Install', to: '/docs/install/installer' },
                { label: 'Tools', to: '/docs/reference/tools' },
                { label: 'Configuration', to: '/docs/reference/configuration' },
                { label: 'Troubleshooting', to: '/docs/guides/troubleshooting' },
              ],
            },
            {
              label: 'Project',
              children: [
                { label: 'GitHub', to: 'https://github.com/bgalmes/rubit-mcp-mail', target: '_blank' },
                { label: 'Issues', to: 'https://github.com/bgalmes/rubit-mcp-mail/issues', target: '_blank' },
                { label: 'Contributing', to: '/docs/about/contributing' },
                { label: 'Contact', to: '/contact' },
              ],
            },
          ]"
        />
      </UContainer>
    </template>

    <template #left>
      <p class="text-sm text-muted">
        &copy; {{ year }} rubit-mcp-mail &middot; Read-only by construction
      </p>
    </template>

    <template #right>
      <UButton
        to="https://github.com/bgalmes/rubit-mcp-mail"
        target="_blank"
        rel="noopener"
        icon="i-simple-icons-github"
        color="neutral"
        variant="ghost"
        aria-label="GitHub"
      />
    </template>
  </UFooter>
</template>
