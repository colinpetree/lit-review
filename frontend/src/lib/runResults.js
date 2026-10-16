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
