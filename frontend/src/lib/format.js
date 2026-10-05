const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function formatNewest(newestYear, newestPublicationDate) {
  if (newestPublicationDate) {
    const [y, m] = newestPublicationDate.split('-')
    const monthIndex = Number(m) - 1
    if (y && monthIndex >= 0 && monthIndex < 12) {
      return `${MONTH_NAMES[monthIndex]} ${y}`
    }
  }
  return newestYear ? `${newestYear}` : null
}

// A run's cost is its grading plus the query expansion of every dataset it uses,
// so a dataset shared by several runs counts its expansion in each of them.
export const RUN_COST_NOTE = 'Grading, plus the query expansion of each dataset used'

// Only web addresses are turned into links: a paper's url comes from outside
// APIs or was typed in, and a javascript: or data: link must never be opened.
export function isHttpUrl(value) {
  return typeof value === 'string' && /^https?:\/\/\S/i.test(value)
}

// Timestamps are stored as UTC ISO strings; show them in the user's locale.
export function formatDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDateTime(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

// Display labels for a run's datasets. Titles aren't unique, so a dataset whose
// title matches another in the list gets its created date and time appended.
export function datasetLabels(datasets) {
  const counts = new Map()
  for (const d of datasets) counts.set(d.name, (counts.get(d.name) ?? 0) + 1)
  return datasets.map((d) =>
    counts.get(d.name) > 1 && formatDateTime(d.created_at)
      ? `${d.name} (${formatDateTime(d.created_at)})`
      : d.name
  )
}

export function formatYearRange(oldestYear, newestYear, newestPublicationDate) {
  if (!oldestYear && !newestYear) return null
  const newestLabel = formatNewest(newestYear, newestPublicationDate)
  if (oldestYear === newestYear) return newestLabel
  return `${oldestYear} - ${newestLabel}`
}
