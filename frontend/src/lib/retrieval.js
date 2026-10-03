// How complete a dataset's searches were. The server records one entry per source and
// query: { source, query, total, fetched, kept, capped, capped_by }, where `total` is how many
// papers the source says match (null if it does not say), `fetched` how many were kept from
// it, `capped` a sentence saying why any were left out (null if none were) and `capped_by`
// whether the user's own limit ('limit') or the source's ('source') stopped it.

const count = (n) => Number(n).toLocaleString('en-US')

// null for a dataset from before this was recorded.
export function summarizeRetrieval(retrieval) {
  if (!Array.isArray(retrieval) || retrieval.length === 0) return null
  const incomplete = retrieval.filter((entry) => entry.capped)
  return {
    complete: incomplete.length === 0,
    incomplete,
    // Why a source itself stopped short, which the user's limit does not explain, each once.
    // The user's own limit needs no note: the numbers beside each search ("100 of 368")
    // already say it. Notes saved without a cause are left out for the same reason.
    reasons: [...new Set(incomplete.filter((entry) => entry.capped_by === 'source').map((entry) => entry.capped))],
  }
}

// "100 of 368" (kept of how many matched), "24 of 24", or "40" when the source does not say
// how many match.
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
