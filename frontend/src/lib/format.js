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

// Timestamps are stored as UTC ISO strings; show them in the user's locale.
export function formatDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatYearRange(oldestYear, newestYear, newestPublicationDate) {
  if (!oldestYear && !newestYear) return null
  const newestLabel = formatNewest(newestYear, newestPublicationDate)
  if (oldestYear === newestYear) return newestLabel
  return `${oldestYear} - ${newestLabel}`
}
