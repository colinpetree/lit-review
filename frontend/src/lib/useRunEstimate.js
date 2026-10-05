import { useEffect, useState } from 'react'
import { postJson } from './api'

// Wait this long after the last change before asking, so typing the grading prompt does
// not send a request per key.
const DEBOUNCE_MS = 600

// The estimated cost of the run the Evaluate form describes: { usd, papers, chunks,
// basis }, or null while it has none. `request` is the body of POST /api/analysis-runs
// (or null when the form is not ready to run), and it is asked again, after a pause,
// whenever that body changes. An answer to an older body is never shown for a newer one.
// `failed` is true when the last request failed, so the form can say the cost is unknown
// instead of showing nothing.
export default function useRunEstimate(request) {
  const key = request ? JSON.stringify(request) : null
  const [answer, setAnswer] = useState({ key: null, estimate: null, failed: false })

  useEffect(() => {
    if (key === null) return undefined
    const controller = new AbortController()
    const timer = setTimeout(() => {
      postJson('/api/analysis-runs/estimate', JSON.parse(key), { signal: controller.signal })
        .then((estimate) => setAnswer({ key, estimate, failed: false }))
        .catch((err) => {
          if (err.name !== 'AbortError') setAnswer({ key, estimate: null, failed: true })
        })
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [key])

  const current = key !== null && answer.key === key
  return {
    estimate: current ? answer.estimate : null,
    failed: current && answer.failed,
    // Asked for, not yet answered.
    loading: key !== null && !current,
  }
}
