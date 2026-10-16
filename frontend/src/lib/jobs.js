// Helpers for the app's background jobs (see backend/jobs.py). The server works out each dataset's and
// evaluation's `state` ("queued", "running", "stopping", "incomplete" or "completed") and its `job`; these
// only decide how often to ask again and how to word what is going on.

export const POLL_FAST_MS = 2500
export const POLL_SLOW_MS = 20000

export const STATE_LABELS = {
  queued: 'Queued',
  running: 'Running',
  stopping: 'Stopping...',
  incomplete: 'Incomplete',
  completed: 'Completed',
}

export const isActiveJob = (job) => job.status === 'queued' || job.status === 'running'

// Whether an item (a dataset or evaluation) has work going on or waiting.
export const isWorking = (item) => ['queued', 'running', 'stopping'].includes(item?.state)

// Whether two job lists say the same thing. The poll keeps the list it already has when nothing changed,
// so a page showing a large dataset or evaluation is not drawn again every few seconds for nothing.
export function sameJobs(a, b) {
  return a === b || JSON.stringify(a) === JSON.stringify(b)
}

// The jobs working on one dataset or evaluation (`field` is "dataset_id" or "run_id").
export const jobsFor = (jobs, field, id) => jobs.filter((job) => job[field] === id)

// Quick while anything is going on, slow otherwise (slowly still, so work started from another tab, or
// queued by a finished search, is noticed).
export function pollDelay(jobs) {
  return jobs.some(isActiveJob) ? POLL_FAST_MS : POLL_SLOW_MS
}

// Changes when a job starts, stops or ends: a page showing a list asks for it again then.
export function statusSignature(jobs) {
  return jobs.map((job) => `${job.id}:${job.status}:${job.stop_requested ? 1 : 0}`).join(',')
}

// Changes whenever an active job moves along (a batch graded, an abstract found): a page showing
// that job's results asks for them again then.
export function progressSignature(jobs) {
  return jobs
    .filter(isActiveJob)
    .map((job) => `${job.id}:${JSON.stringify(job.progress ?? {})}`)
    .join('|')
}

// A few words on how far along a job is, or null.
export function progressText(job) {
  if (!job) return null
  const p = job.progress ?? {}
  if (job.kind === 'run_score') return p.total ? `${p.done ?? 0} of ${p.total} graded` : null
  if (job.kind === 'find_abstracts') return p.total ? `${p.attempted ?? 0} of ${p.total} looked up` : null
  if (p.stage && p.stage !== 'Done') {
    return p.total && p.done != null ? `${p.stage} ${p.done} of ${p.total}` : p.stage
  }
  return null
}

// What a job is doing, for the item's page: "Looking up abstracts", "Grading papers"...
export function jobActivity(job) {
  if (!job) return null
  return (
    {
      run_score: 'Grading papers',
      find_abstracts: 'Looking up abstracts',
      dataset_search: 'Searching for papers',
      dataset_refresh: 'Checking for new papers',
    }[job.kind] ?? 'Working'
  )
}
