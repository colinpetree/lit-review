import { useCallback, useEffect, useState } from 'react'
import { fetchJson, postJson } from './api'

// Which API keys are saved (GET /api/settings/api-key; null while loading, and `store_error`
// when the saved-keys file cannot be read) and how to save or remove one. Used by the two
// pages that hold key cards.
export default function useApiKeys() {
  const [keyStatus, setKeyStatus] = useState(null)

  const refresh = useCallback(() => {
    fetchJson('/api/settings/api-key')
      .then(setKeyStatus)
      .catch(() => setKeyStatus({}))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const saveKey = async (provider, apiKey) => {
    await postJson('/api/settings/api-key', { provider, api_key: apiKey })
    refresh()
  }

  const deleteKey = async (provider) => {
    await fetchJson('/api/settings/api-key', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    })
    refresh()
  }

  return { keyStatus, saveKey, deleteKey }
}
