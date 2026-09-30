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

export function formatYearRange(oldestYear, newestYear, newestPublicationDate) {
  if (!oldestYear && !newestYear) return null
  const newestLabel = formatNewest(newestYear, newestPublicationDate)
  if (oldestYear === newestYear) return newestLabel
  return `${oldestYear} - ${newestLabel}`
}
