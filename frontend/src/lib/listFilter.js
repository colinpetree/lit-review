// Search, date range, model filter and newest/oldest sort shared by the Paper
// Paper Datasets, Results and Scoring Prompts lists.

export const EMPTY_LIST_FILTER = { query: '', dateFrom: '', dateTo: '', model: '' }

export const DEFAULT_LIST_SORT = 'newest'

export const LIST_SORT_OPTIONS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'oldest', label: 'Oldest first' },
]

export const modelKey = (aiApi, aiModel) => `${aiApi}::${aiModel}`

// The date fields are typed text, so a date only counts once it is complete.
export const isFullDate = (value) => /^\d{4}-\d{2}-\d{2}$/.test(value)

export function isListFilterActive(filter) {
  return Boolean(
    filter.query.trim() || isFullDate(filter.dateFrom) || isFullDate(filter.dateTo) || filter.model
  )
}

// The date inputs give local calendar days ("2026-03-05"), so the item's UTC
// timestamp is compared as the user's local day, with both ends inclusive.
function localDay(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// getSearchText(item) returns the text the typed query is matched against;
// getModel(item) (optional) returns the item's modelKey, or null if it has none.
// Every whitespace-separated term must appear, case-insensitive.
export function filterList(items, filter, { getSearchText, getModel }) {
  if (!isListFilterActive(filter)) return items
  const terms = filter.query.toLowerCase().split(/\s+/).filter(Boolean)
  const dateFrom = isFullDate(filter.dateFrom) ? filter.dateFrom : ''
  const dateTo = isFullDate(filter.dateTo) ? filter.dateTo : ''
  return items.filter((item) => {
    if (dateFrom || dateTo) {
      const day = localDay(item.created_at)
      if (day === null) return false
      if (dateFrom && day < dateFrom) return false
      if (dateTo && day > dateTo) return false
    }
    if (filter.model && getModel?.(item) !== filter.model) return false
    if (!terms.length) return true
    const text = getSearchText(item).toLowerCase()
    return terms.every((term) => text.includes(term))
  })
}

// Timestamps are ISO strings, so they compare correctly as text. Ties (and
// missing timestamps) fall back to id so the order is stable.
export function sortByCreated(items, sort) {
  const sign = sort === 'oldest' ? 1 : -1
  return [...items].sort((a, b) => {
    const ka = a.created_at ?? ''
    const kb = b.created_at ?? ''
    if (ka !== kb) return ka < kb ? -sign : sign
    return a.id < b.id ? -sign : a.id > b.id ? sign : 0
  })
}
