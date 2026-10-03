// How many of the most relevant papers each search keeps (per query, per source). A dataset
// is meant to be a narrow dive on one topic, and datasets can be pooled when evaluating, so
// the way to cover more is several narrower datasets. Mirrors search_sources.py by hand
// (SEARCH_LIMIT_CHOICES and DEFAULT_SEARCH_LIMIT); the server refuses anything else.

export const DEFAULT_SEARCH_LIMIT = 100

export const SEARCH_LIMIT_OPTIONS = [
  { value: 50, label: '50 most relevant', hint: 'tightest' },
  { value: 100, label: '100 most relevant', hint: 'default' },
  { value: 200, label: '200 most relevant' },
  { value: 500, label: '500 most relevant', hint: 'broad' },
]

// A remembered value that is not a current choice falls back to the default.
export function normalizeSearchLimit(value) {
  return SEARCH_LIMIT_OPTIONS.some((option) => option.value === value) ? value : DEFAULT_SEARCH_LIMIT
}
