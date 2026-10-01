import { postJson } from './api'

// Calls the dataset's find-abstracts endpoint until every paper that has a DOI,
// no abstract and no completed lookup yet has been tried, like
// driveAnalysisRun does for scoring. The server is stateless, so this sends
// back the paper ids already tried and the sources that failed.
//
// onProgress({ filled, checked, filledCount, attempted, total, sourceErrors,
// noDoi }) fires after each chunk with that chunk's filled papers and the ids
// the server marked as checked (no abstract found); the returned object is the
// same shape, accumulated over the whole run. `total` is how many papers this
// run covers.
export async function driveFindAbstracts(datasetId, signal, onProgress) {
  const attemptedIds = []
  const sourceErrors = {}
  let filledCount = 0
  let noDoi = 0
  let total = null

  for (;;) {
    const chunk = await postJson(
      `/api/datasets/${datasetId}/find-abstracts`,
      { skip_ids: attemptedIds, skip_sources: Object.keys(sourceErrors) },
      { signal }
    )
    if (total === null) total = chunk.attempted.length + chunk.remaining
    attemptedIds.push(...chunk.attempted)
    Object.assign(sourceErrors, chunk.source_errors)
    filledCount += chunk.filled.length
    noDoi = chunk.no_doi

    const progress = {
      filled: chunk.filled,
      checked: chunk.checked,
      filledCount,
      attempted: attemptedIds.length,
      total,
      sourceErrors: { ...sourceErrors },
      noDoi,
    }
    onProgress(progress)

    // An empty chunk means nothing was left to try, which also guards against
    // looping forever if `remaining` were ever wrong.
    if (chunk.remaining <= 0 || chunk.attempted.length === 0) return progress
  }
}

// Lookups live here, outside any React component, so one keeps running when
// the user navigates away from the dataset page (the app is a single-page app,
// so this module stays loaded). A page re-attaches with getLookup/subscribeLookup.
// Each state also carries `filledPapers` and `checkedIds` accumulated over the
// whole run, so a page opened mid-run can catch up on what it missed.
const lookups = new Map() // datasetId -> { state }
const listeners = new Map() // datasetId -> Set of fn, kept apart so a page can subscribe before a run starts

export function getLookup(datasetId) {
  return lookups.get(datasetId)?.state ?? null
}

// fn(state) fires after every chunk and once more when the run ends (running
// false), after which the lookup is forgotten. Returns an unsubscribe function.
export function subscribeLookup(datasetId, fn) {
  if (!listeners.has(datasetId)) listeners.set(datasetId, new Set())
  listeners.get(datasetId).add(fn)
  return () => listeners.get(datasetId)?.delete(fn)
}

// Starts a lookup unless one is already running for this dataset.
export function startLookup(datasetId) {
  if (lookups.has(datasetId)) return
  const entry = {
    state: {
      running: true,
      total: null,
      attempted: 0,
      filledCount: 0,
      sourceErrors: {},
      noDoi: 0,
      filledPapers: [],
      checkedIds: [],
    },
  }
  lookups.set(datasetId, entry)
  const publish = (patch) => {
    entry.state = { ...entry.state, ...patch }
    listeners.get(datasetId)?.forEach((fn) => fn(entry.state))
  }
  publish({})

  driveFindAbstracts(datasetId, undefined, (progress) => {
    publish({
      ...progress,
      filledPapers: [...entry.state.filledPapers, ...progress.filled],
      checkedIds: [...entry.state.checkedIds, ...progress.checked],
      running: true,
    })
  })
    .then((result) => publish({ ...result, filled: [], checked: [], running: false }))
    .catch((err) => publish({ running: false, error: err.message }))
    .finally(() => lookups.delete(datasetId))
}
