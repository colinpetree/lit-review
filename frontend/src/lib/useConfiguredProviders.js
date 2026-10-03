import { useEffect, useState } from 'react'
import { fetchJson } from './api'

// { anthropic: true } etc - which providers GET /api/settings/api-key
// reports as having a key configured. null while loading.
export default function useConfiguredProviders() {
  const [providers, setProviders] = useState(null)

  useEffect(() => {
    fetchJson('/api/settings/api-key')
      .then(setProviders)
      .catch(() => setProviders({}))
  }, [])

  return providers
}
