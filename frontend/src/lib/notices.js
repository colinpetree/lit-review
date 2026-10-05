import { useCallback, useEffect, useState } from 'react'
import { fetchJson } from './api'

// The third-party notices come from the app (it reads the file the build shipped). They are
// a few hundred KB and never change while the app runs, so once fetched they are kept for
// the life of the page and reopening the dialog does not ask again. A failure is not kept.
let cached = null

export async function fetchNotices() {
  if (cached !== null) return cached
  const data = await fetchJson('/api/notices')
  if (typeof data?.text !== 'string' || !data.text.trim()) throw new Error('Unexpected response from the server.')
  cached = data.text
  return cached
}

export function forgetNotices() {
  cached = null
}

// { text, error, loading, retry } for the dialog: loads once when it opens, and again on retry.
export function useNotices() {
  const [state, setState] = useState({ text: cached, error: null, loading: cached === null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (cached !== null) return undefined
    let cancelled = false
    fetchNotices()
      .then((text) => {
        if (!cancelled) setState({ text, error: null, loading: false })
      })
      .catch((err) => {
        if (!cancelled) setState({ text: null, error: err.message || 'The notices could not be loaded.', loading: false })
      })
    return () => {
      cancelled = true
    }
  }, [attempt])

  const retry = useCallback(() => {
    setState({ text: null, error: null, loading: true })
    setAttempt((n) => n + 1)
  }, [])
  return { ...state, retry }
}
