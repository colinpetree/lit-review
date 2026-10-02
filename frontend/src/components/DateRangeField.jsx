import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

// The condensed text shown while the popover is closed.
function rangeText(from, to) {
  if (from && to) return `${from}-${to}`
  if (from) return `${from}-present`
  if (to) return `Up to ${to}`
  return 'All time'
}

// A year range shown as one short button ("All time", "1950-2026", "Up to 2020",
// "2020-present"). Clicking opens a popover below it with the From and To year
// inputs and a Clear Dates link; clicking outside or pressing Escape closes it.
export default function DateRangeField({ fromYear, toYear, onFromChange, onToChange, disabled }) {
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
        className="w-full rounded-md border border-gray-300 bg-white py-2 pl-3 pr-9 text-left text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
      >
        {rangeText(fromYear, toYear)}
      </button>
      <ChevronDown size={16} className="pointer-events-none absolute right-3 top-3 text-gray-400" />
      {open ? (
        <div
          role="dialog"
          aria-label="Dates"
          className="absolute left-0 top-full z-20 mt-1 flex w-full flex-col gap-3 rounded-xl border border-gray-200 bg-white p-3 shadow-lg"
        >
          <div className="flex gap-3">
            {[
              ['From year', fromYear, onFromChange],
              ['To year', toYear, onToChange],
            ].map(([label, value, onChange]) => (
              <div key={label}>
                <label className="block text-xs text-gray-500">{label}</label>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={4}
                  value={value}
                  onChange={(e) => onChange(e.target.value.replace(/\D/g, ''))}
                  className="mt-1 w-24 rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              onFromChange('')
              onToChange('')
            }}
            disabled={!fromYear && !toYear}
            className="self-start text-sm text-gray-500 underline hover:text-gray-700 disabled:opacity-40 disabled:no-underline"
          >
            Clear Dates
          </button>
        </div>
      ) : null}
    </div>
  )
}
