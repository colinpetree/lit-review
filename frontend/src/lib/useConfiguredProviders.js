import { useEffect, useState } from 'react'

// { anthropic: true } etc - which providers GET /api/settings/api-key
// reports as having a key configured. null while loading.
export default function useConfiguredProviders() {
  const [providers, setProviders] = useState(null)

  useEffect(() => {
    fetch('/api/settings/api-key')
      .then((res) => res.json())
      .then(setProviders)
      .catch(() => setProviders({}))
  }, [])

  return providers
}
