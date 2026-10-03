import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import DatePicker from './DatePicker'
import { cleanDateInput, formatBound } from '../lib/dateRange'

// The condensed text shown while the popover is closed. Each end is a year or a
// month or full date (shown like "Aug 2026" or "Aug 30, 2026").
function rangeText(fromDate, toDate) {
  const from = formatBound(fromDate)
  const to = formatBound(toDate)
  if (from && to) return `${from} - ${to}`
  if (from) return `${from} - present`
  if (to) return `Up to ${to}`
  return 'All time'
}

// A publication date range shown as one short button ("All time", "1950 -
// 2026", "Up to 2020", "Mar 5, 2026 - present"). Clicking opens a popover below it
// with the From and To fields and a Clear Dates link; clicking outside or pressing
// Escape closes it. Each field takes a year ("2026"), a month ("2026-03") or a
// date ("2026-03-05") typed in, and opens a calendar to pick a date when it is clicked.
export default function DateRangeField({ fromDate, toDate, onFromChange, onToChange, disabled }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={ref} className="relative mt-1 max-w-xs">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="pick-button w-full rounded-md border border-gray-300 bg-surface py-2 pl-3 pr-9 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
      >
        {rangeText(fromDate, toDate)}
      </button>
      <ChevronDown size={16} className="pointer-events-none absolute right-3 top-3 text-gray-400" />
      {open ? (
        <div
          role="dialog"
          aria-label="Publication dates"
          className="absolute left-0 top-full z-20 mt-1 flex w-full flex-col gap-3 rounded-xl border border-gray-200 bg-surface p-3 shadow-lg"
        >
          <div className="flex gap-3">
            <div className="min-w-0 flex-1">
              <label className="block text-xs text-gray-500">From</label>
              <DatePicker
                ariaLabel="From year, month or date"
                placeholder="Date"
                value={fromDate}
                onChange={(v) => onFromChange(cleanDateInput(v))}
                className="mt-1"
              />
            </div>
            <div className="min-w-0 flex-1">
              <label className="block text-xs text-gray-500">To</label>
              <DatePicker
                ariaLabel="To year, month or date"
                placeholder="Date"
                align="right"
                value={toDate}
                onChange={(v) => onToChange(cleanDateInput(v))}
                className="mt-1"
              />
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              onFromChange('')
              onToChange('')
            }}
            disabled={!fromDate && !toDate}
            className="self-start text-sm text-gray-500 underline hover:text-gray-700 disabled:opacity-40 disabled:no-underline"
          >
            Clear dates
          </button>
        </div>
      ) : null}
    </div>
  )
}
