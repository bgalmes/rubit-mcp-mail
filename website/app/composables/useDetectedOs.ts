export type DetectedOs = 'windows' | 'linux' | 'macos' | 'unknown'

/**
 * Best-effort client-side OS sniff, used only to pick which download to offer
 * first. It resolves to 'unknown' during prerender so the server-rendered HTML
 * is platform-neutral and hydration never mismatches; the real value lands on
 * mount. Every platform stays reachable regardless of what this returns.
 */
export function useDetectedOs() {
  const os = ref<DetectedOs>('unknown')

  onMounted(() => {
    const ua = navigator.userAgent
    // Check Windows before the generic checks: "Windows NT" contains neither
    // "Mac" nor "Linux", but Android UA strings contain "Linux".
    if (/Win/i.test(ua)) os.value = 'windows'
    else if (/Android/i.test(ua)) os.value = 'linux'
    else if (/Mac|iPhone|iPad/i.test(ua)) os.value = 'macos'
    else if (/Linux|X11|CrOS/i.test(ua)) os.value = 'linux'
  })

  return os
}
