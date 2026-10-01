export const EMPTY_PAPER_FILTER = {
  query: '',
  missingAbstractOnly: false,
  yearFrom: '',
  yearTo: '',
  minCitations: '',
  readState: 'all', // 'all' | 'read' | 'unread'
  relevance: 'all', // 'all' | 'relevant' | 'neutral' | 'not_relevant' (run results only)
}

export const DEFAULT_PAPER_SORT = 'date-desc'

export const PAPER_SORT_OPTIONS = [
  { value: 'date-desc', label: 'Newest first' },
  { value: 'date-asc', label: 'Oldest first' },
  { value: 'citations-desc', label: 'Most cited' },
  { value: 'citations-asc', label: 'Least cited' },
]

function toNumber(value) {
  if (value === '' || value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function isPaperFilterActive(filter) {
  return (
    Boolean(filter.query.trim()) ||
    filter.missingAbstractOnly ||
    toNumber(filter.yearFrom) !== null ||
    toNumber(filter.yearTo) !== null ||
    toNumber(filter.minCitations) !== null ||
    filter.readState !== 'all' ||
    filter.relevance !== 'all'
  )
}

// Every whitespace-separated term in the query must appear (case-insensitive)
// somewhere in the paper's title, authors, venue, year or abstract.
export function filterPapers(papers, filter) {
  if (!isPaperFilterActive(filter)) return papers
  const terms = filter.query.toLowerCase().split(/\s+/).filter(Boolean)
  const yearFrom = toNumber(filter.yearFrom)
  const yearTo = toNumber(filter.yearTo)
  const minCitations = toNumber(filter.minCitations)
  return papers.filter((paper) => {
    if (filter.missingAbstractOnly && (paper.abstract || '').trim()) return false
    if (filter.readState === 'read' && !paper.read) return false
    if (filter.readState === 'unread' && paper.read) return false
    // Papers without a result yet have no relevance, which counts as neutral.
    if (filter.relevance !== 'all' && (paper.relevance || 'neutral') !== filter.relevance) return false
    if (yearFrom !== null && !(paper.year >= yearFrom)) return false
    if (yearTo !== null && !(paper.year <= yearTo)) return false
    if (minCitations !== null && !((paper.citation_count ?? 0) >= minCitations)) return false
    if (!terms.length) return true
    const haystack = [paper.title, (paper.authors || []).join(' '), paper.venue, paper.year, paper.abstract]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    return terms.every((term) => haystack.includes(term))
  })
}

// Publication dates are ISO strings, so they compare correctly as text; the
// year stands in when a source gave no full date. Papers missing the sort
// value always go last, in either direction.
function dateKey(paper) {
  return paper.publication_date || (paper.year ? String(paper.year) : null)
}

export function sortPapers(papers, sort) {
  const [field, direction] = sort.split('-')
  const sign = direction === 'asc' ? 1 : -1
  const key = field === 'citations' ? (p) => p.citation_count ?? null : dateKey
  return [...papers].sort((a, b) => {
    const ka = key(a)
    const kb = key(b)
    if (ka === null && kb === null) return 0
    if (ka === null) return 1
    if (kb === null) return -1
    return ka < kb ? -sign : ka > kb ? sign : 0
  })
}
