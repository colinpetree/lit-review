// How complete a dataset's searches were. The server records one entry per source and
// query: { source, query, total, fetched, kept, capped }, where `total` is how many
// papers the source says match (null if it does not say), `fetched` how many it
// returned, and `capped` a sentence saying why any were left out (null if none were).

const count = (n) => Number(n).toLocaleString('en-US')

// null for a dataset from before this was recorded.
export function summarizeRetrieval(retrieval) {
  if (!Array.isArray(retrieval) || retrieval.length === 0) return null
  const incomplete = retrieval.filter((entry) => entry.capped)
  return {
    complete: incomplete.length === 0,
    incomplete,
    // The distinct reasons, so a dozen searches stopped by one limit say it once.
    reasons: [...new Set(incomplete.map((entry) => entry.capped))],
  }
}

// "120 of 120", "50 of 3,200", or "120" when the source does not say how many match.
export function hitsText(entry) {
  if (entry.total == null) return count(entry.fetched)
  return `${count(entry.fetched)} of ${count(entry.total)}`
}

// The entries grouped by source, in the order the sources first appear.
export function groupBySource(retrieval) {
  const groups = new Map()
  for (const entry of retrieval || []) {
    if (!groups.has(entry.source)) groups.set(entry.source, [])
    groups.get(entry.source).push(entry)
  }
  return [...groups].map(([source, entries]) => ({ source, entries }))
}
