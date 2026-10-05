import { postJson } from './api'

// Merges a run's graded results onto its full candidate_papers list, so
// still-ungraded papers stay visible (without a grade badge) instead of
// only showing whatever's graded so far - the same merge-not-replace idea
// the single-dataset flow used, generalized to a run's candidate_papers
// field since a multi-dataset run has no single source paper list to merge
// onto otherwise.
export function mergeRunResults(run) {
  const byId = new Map(run.candidate_papers.map((p) => [p.id, p]))
  for (const scored of run.results) byId.set(scored.id, scored)
  const merged = [...byId.values()].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
  return { ...run, results: merged }
}

// The server grades one chunk of a run at a time (409 = busy). Stopping a
// request in the browser does not stop the server's call to the AI model, so
// after Stop then Resume the old chunk is often still running: wait for it
// instead of failing, for about a minute.
const BUSY_RETRY_MS = 2000
const BUSY_MAX_RETRIES = 30

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'))
    const onAbort = () => {
      clearTimeout(timer)
      reject(new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

// Repeatedly processes one grading chunk at a time until the run is
// completed, calling onUpdate after every chunk with the merged run object.
export async function driveAnalysisRun(runId, signal, onUpdate, { busyRetryMs = BUSY_RETRY_MS } = {}) {
  let run
  let busyRetries = 0
  for (;;) {
    try {
      run = await postJson(`/api/analysis-runs/${runId}/process`, {}, { signal })
    } catch (err) {
      if (err.status !== 409 || busyRetries >= BUSY_MAX_RETRIES) throw err
      busyRetries += 1
      await sleep(busyRetryMs, signal)
      continue
    }
    busyRetries = 0
    onUpdate(mergeRunResults(run))
    if (run.status === 'completed') break
  }
  return run
}
