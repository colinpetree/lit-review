import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { fetchJson, postJson } from '../lib/api'
import { pollDelay, progressSignature, sameJobs, statusSignature } from '../lib/jobs'

const noop = async () => null
const JobsContext = createContext({
  jobs: [],
  statusKey: '',
  progressKey: '',
  refreshJobs: noop,
  startJob: noop,
  stopJob: noop,
  resumeJob: noop,
})

// The app's background jobs (searches, evaluations, abstract lookups), kept fresh: asked for every couple
// of seconds while any is going, and every 20 seconds otherwise. Pages never wait for a job; they show
// what this says and ask for their own data again when `statusKey` (a job started, stopped or ended) or
// `progressKey` (a job moved along) changes. A failed ask keeps the last answer: the app being briefly
// unreachable is not something to show on a page.
export function JobsProvider({ children }) {
  const [jobs, setJobs] = useState([])
  const timer = useRef(null)
  const alive = useRef(true)
  const last = useRef([])

  const refreshJobs = useCallback(async function poll() {
    clearTimeout(timer.current)
    let next = last.current
    try {
      const data = await fetchJson('/api/jobs')
      next = data.jobs ?? []
      if (alive.current) {
        last.current = next
        // The same list again keeps the same array, so nothing that reads it is drawn again.
        setJobs((prev) => (sameJobs(prev, next) ? prev : next))
      }
    } catch {
      // keep the last answer
    }
    if (alive.current) timer.current = setTimeout(poll, pollDelay(next))
    return next
  }, [])

  useEffect(() => {
    alive.current = true
    refreshJobs()
    return () => {
      alive.current = false
      clearTimeout(timer.current)
    }
  }, [refreshJobs])

  // Each of these answers when the app has done it, and then asks for the jobs again so the page shows it.
  const startJob = useCallback(
    async (fields) => {
      const result = await postJson('/api/jobs', fields)
      await refreshJobs()
      return result
    },
    [refreshJobs],
  )
  const stopJob = useCallback(
    async (id) => {
      const result = await postJson(`/api/jobs/${id}/stop`, {})
      await refreshJobs()
      return result
    },
    [refreshJobs],
  )
  const resumeJob = useCallback(
    async (id) => {
      const result = await postJson(`/api/jobs/${id}/resume`, {})
      await refreshJobs()
      return result
    },
    [refreshJobs],
  )

  const statusKey = useMemo(() => statusSignature(jobs), [jobs])
  const progressKey = useMemo(() => progressSignature(jobs), [jobs])
  const value = useMemo(
    () => ({ jobs, statusKey, progressKey, refreshJobs, startJob, stopJob, resumeJob }),
    [jobs, statusKey, progressKey, refreshJobs, startJob, stopJob, resumeJob],
  )

  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>
}

export const useJobs = () => useContext(JobsContext)
