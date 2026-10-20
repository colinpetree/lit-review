import Spinner from './Spinner'
import { Tooltip } from './ui/Tooltip'
import { useJobs } from './JobsProvider'
import { STATE_LABELS, progressText } from '../lib/jobs'

const STYLES = {
  queued: 'bg-gray-100 text-gray-700',
  running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  stopping: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  incomplete: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  completed: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
}

const DOT_STYLES = {
  queued: 'bg-gray-400',
  incomplete: 'bg-amber-500',
}

// The same state as a small mark for a table row (a spinner while running or stopping, else a colored
// dot), shown only when something is under way or went wrong: Queued, Running, Stopping or Incomplete. A completed item shows nothing, so the usual case
// draws no attention. The state's name (and an incomplete one's reason) is in the app's tooltip.
export function JobStatusDot({ item }) {
  const { jobs } = useJobs()
  const state = item?.state
  if (!state || state === 'completed') return null
  const job = (item.job && jobs.find((j) => j.id === item.job.id)) || item.job
  const label = STATE_LABELS[state] ?? state
  const reason = state === 'incomplete' ? job?.error : null
  const content = reason ? (
    <span className="block max-w-xs whitespace-normal">
      {label}: <span className="font-normal">{reason}</span>
    </span>
  ) : (
    label
  )
  return (
    <Tooltip content={content}>
      {state === 'running' || state === 'stopping' ? (
        <span aria-label={label} role="img" className="inline-flex shrink-0 items-center">
          <Spinner className="h-3.5 w-3.5" />
        </span>
      ) : (
        <span
          aria-label={reason ? `${label}: ${reason}` : label}
          role="img"
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT_STYLES[state] ?? DOT_STYLES.queued}`}
        />
      )}
    </Tooltip>
  )
}

// A dataset's or evaluation's state as a small pill: Queued, Running (with how far along), Incomplete (the
// reason on hover) or Completed. `item` carries `state` and `job` from the server; how far along comes from
// the live job list, which is newer than the page's own copy.
// hideCompleted leaves a completed item with no pill, for lists where only work under way or gone wrong
// should draw attention.
export default function JobStatus({ item, showProgress = true, hideCompleted = false, className = '' }) {
  const { jobs } = useJobs()
  const state = item?.state
  if (!state || (hideCompleted && state === 'completed')) return null
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
