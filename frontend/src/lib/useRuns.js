import { useEffect, useRef, useState } from 'react'
import { fetchJson } from './api'
import { useJobs } from '../components/JobsProvider'

// Every live evaluation (GET /api/analysis-runs), null while loading. Loaded again whenever a job
// starts, stops or ends, so each row's status stays true. A failed reload keeps the list that is
// showing; only the first load reports an error. `setRuns` is for changes the page made itself
// (a rename, a delete).
export default function useRuns() {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  const { statusKey } = useJobs()
  const loaded = useRef(false)

  useEffect(() => {
    let cancelled = false
    fetchJson('/api/analysis-runs')
      .then((data) => {
        if (cancelled) return
        loaded.current = true
        setRuns(data.runs ?? [])
        setError(null)
      })
      .catch((err) => {
        if (!cancelled && !loaded.current) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [statusKey])

  return { runs, setRuns, error }
}
