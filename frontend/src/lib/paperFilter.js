export const EMPTY_PAPER_FILTER = { query: '', missingAbstractOnly: false }

export function isPaperFilterActive(filter) {
  return Boolean(filter.query.trim()) || filter.missingAbstractOnly
}

// Every whitespace-separated term in the query must appear (case-insensitive)
// somewhere in the paper's title, authors, venue, year or abstract.
export function filterPapers(papers, filter) {
  const terms = filter.query.toLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length && !filter.missingAbstractOnly) return papers
  return papers.filter((paper) => {
    if (filter.missingAbstractOnly && (paper.abstract || '').trim()) return false
    if (!terms.length) return true
    const haystack = [paper.title, (paper.authors || []).join(' '), paper.venue, paper.year, paper.abstract]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return terms.every((term) => haystack.includes(term))
  })
}
