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
