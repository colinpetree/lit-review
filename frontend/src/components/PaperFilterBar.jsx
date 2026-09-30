import { useEffect, useRef, useState } from 'react'
import { Search, SlidersHorizontal, X } from 'lucide-react'
import { EMPTY_PAPER_FILTER, isPaperFilterActive } from '../lib/paperFilter'

// Search box (filters on every keystroke) plus a popover of extra filters.
// shown/total are the filtered and unfiltered paper counts, used for the
// "Showing X of Y" line while a filter is active.
export default function PaperFilterBar({ filter, onChange, shown, total }) {
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

  const active = isPaperFilterActive(filter)

  return (
    <div className="mt-4">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={filter.query}
            onChange={(e) => onChange({ ...filter, query: e.target.value })}
            placeholder="Filter papers by title, author, venue or abstract"
            className="w-full rounded-md border border-gray-300 py-2 pl-9 pr-8 text-sm text-gray-900"
          />
          {filter.query ? (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => onChange({ ...filter, query: '' })}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-gray-400 hover:text-gray-600"
            >
              <X size={14} />
            </button>
          ) : null}
        </div>

        <div ref={ref} className="relative">
          <button
            type="button"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className={`relative flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm hover:bg-gray-100 ${
              filter.missingAbstractOnly ? 'border-blue-300 text-blue-700' : 'border-gray-300 text-gray-700'
            }`}
          >
            <SlidersHorizontal size={14} />
            Filters
            {filter.missingAbstractOnly ? (
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-blue-600" />
            ) : null}
          </button>
          {open ? (
            <div className="absolute right-0 z-10 mt-1 w-64 rounded-md border border-gray-200 bg-white p-3 shadow-lg">
              <div className="flex items-center justify-between gap-3 text-sm text-gray-700">
                <span id="missing-abstract-label">Only papers without abstracts</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={filter.missingAbstractOnly}
                  aria-labelledby="missing-abstract-label"
                  onClick={() => onChange({ ...filter, missingAbstractOnly: !filter.missingAbstractOnly })}
                  className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                    filter.missingAbstractOnly ? 'bg-blue-600' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                      filter.missingAbstractOnly ? 'translate-x-4' : ''
                    }`}
                  />
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {active ? (
        <p className="mt-2 text-sm text-gray-500">
          Showing {shown} of {total} papers ·{' '}
          <button
            type="button"
            onClick={() => onChange(EMPTY_PAPER_FILTER)}
            className="text-blue-600 hover:underline"
          >
            Clear filters
          </button>
        </p>
      ) : null}
    </div>
  )
}
