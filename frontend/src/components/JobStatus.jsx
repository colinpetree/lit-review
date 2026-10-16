import Spinner from './Spinner'
import { useJobs } from './JobsProvider'
import { STATE_LABELS, progressText } from '../lib/jobs'

const STYLES = {
  queued: 'bg-gray-100 text-gray-700',
  running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  stopping: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  incomplete: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  completed: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
}

// A dataset's or evaluation's state as a small pill: Queued, Running (with how far along), Incomplete (the
// reason on hover) or Completed. `item` carries `state` and `job` from the server; how far along comes from
// the live job list, which is newer than the page's own copy.
export default function JobStatus({ item, showProgress = true, className = '' }) {
  const { jobs } = useJobs()
  const state = item?.state
  if (!state) return null
  const job = (item.job && jobs.find((j) => j.id === item.job.id)) || item.job
  const working = state === 'running' || state === 'stopping'
  const progress = working && showProgress ? progressText(job) : null
  return (
    <span
      title={state === 'incomplete' ? (job?.error ?? undefined) : undefined}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${STYLES[state] ?? STYLES.queued} ${className}`}
    >
      {working ? <Spinner className="h-3 w-3" /> : null}
      {STATE_LABELS[state] ?? state}
      {progress ? <span className="font-normal opacity-80">· {progress}</span> : null}
    </span>
  )
}
