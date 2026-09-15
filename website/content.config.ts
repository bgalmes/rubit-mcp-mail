import { defineCollection, defineContentConfig, z } from '@nuxt/content'

export default defineContentConfig({
  collections: {
    docs: defineCollection({
      type: 'page',
      source: 'docs/**/*.md',
      schema: z.object({
        title: z.string(),
        description: z.string(),
        // Lucide/Iconify name shown beside the entry in the sidebar.
        icon: z.string().optional(),
        // Short label for the sidebar when the title is too long for it.
        navTitle: z.string().optional(),
      }),
    }),
  },
})
