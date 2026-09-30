import { postJson } from './api'

// Merges a run's scored results onto its full candidate_papers list, so
// still-unscored papers stay visible (without a score badge) instead of
// only showing whatever's scored so far - the same merge-not-replace idea
// the single-dataset flow used, generalized to a run's candidate_papers
// field since a multi-dataset run has no single source paper list to merge
// onto otherwise.
export function mergeRunResults(run) {
  const byId = new Map(run.candidate_papers.map((p) => [p.id, p]))
  for (const scored of run.results) byId.set(scored.id, scored)
  const merged = [...byId.values()].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
  return { ...run, results: merged }
}

// Repeatedly processes one scoring chunk at a time until the run is
// completed, calling onUpdate after every chunk with the merged run object.
export async function driveAnalysisRun(runId, signal, onUpdate) {
  let run
  for (;;) {
    run = await postJson(`/api/analysis-runs/${runId}/process`, {}, { signal })
    onUpdate(mergeRunResults(run))
    if (run.status === 'completed') break
  }
  return run
}
