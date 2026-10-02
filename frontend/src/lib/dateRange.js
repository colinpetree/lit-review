// The Discover Papers publication date range. Each end is typed (or picked from
// the calendar) as a year ("2026"), a month ("2026-03") or a full date
// ("2026-03-05"). A year or month means its first day for the From end and its
// last day for the To end, so typing just years works as it always has.
const YEAR = /^\d{4}$/
const MONTH = /^\d{4}-\d{2}$/
const DATE = /^\d{4}-\d{2}-\d{2}$/

function isRealDate(text) {
  const [y, m, d] = text.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d
}

// "YYYY-MM-DD" for one typed end, null when it is empty, undefined when it is not
// a year, month or real date.
function bound(text, isEnd) {
  const value = text.trim()
  if (!value) return null
  if (YEAR.test(value) && Number(value) >= 1) return isEnd ? `${value}-12-31` : `${value}-01-01`
  if (MONTH.test(value)) {
    const [y, m] = value.split('-').map(Number)
    if (y < 1 || m < 1 || m > 12) return undefined
    return `${value}-${isEnd ? String(new Date(y, m, 0).getDate()).padStart(2, '0') : '01'}`
  }
  if (DATE.test(value) && isRealDate(value)) return value
  return undefined
}

// What the fields must be fixed to before searching, or null if they are fine.
export function dateRangeError(fromText, toText) {
  const from = bound(fromText, false)
  const to = bound(toText, true)
  if (from === undefined || to === undefined) {
    return 'Enter each publication date as a year (2026), a month (2026-03) or a date (2026-03-05).'
  }
  if (from && to && from > to) return 'The "from" publication date is after the "to" date.'
  return null
}

// { from, to } as "YYYY-MM-DD" or null, for a range dateRangeError accepted.
export function dateBounds(fromText, toText) {
  return { from: bound(fromText, false), to: bound(toText, true) }
}

// One typed end as shown on the closed button: a full date as "Aug 30, 2026", a
// month as "Aug 2026", a year or anything not (yet) valid as typed.
export function formatBound(text) {
  const value = text.trim()
  if (MONTH.test(value) && bound(value, false)) {
    const [y, m] = value.split('-').map(Number)
    return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
  }
  if (!DATE.test(value) || !isRealDate(value)) return value
  const [y, m, d] = value.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Keeps what is typed to something a year or date can be: digits and dashes, at
// most "YYYY-MM-DD" long.
export function cleanDateInput(text) {
  return text.replace(/[^\d-]/g, '').slice(0, 10)
}
