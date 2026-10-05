import { useEffect, useState } from 'react'
import { fetchJson } from './api'
import { useSettingsModal } from '../components/SettingsModalProvider'

// { anthropic: true } etc - which providers GET /api/settings/api-key
// reports as having a key configured. null while loading. Read again each time Settings closes.
export default function useConfiguredProviders() {
  const [providers, setProviders] = useState(null)
  const { settingsVersion } = useSettingsModal()

  useEffect(() => {
    // An answer that arrives after a newer request started (or after unmount) is dropped.
    let current = true
    fetchJson('/api/settings/api-key')
      .then((result) => current && setProviders(result))
      // A failed re-read keeps what was already known instead of showing "no keys".
      .catch(() => current && setProviders((known) => known ?? {}))
    return () => {
      current = false
    }
  }, [settingsVersion])

  return providers
}
