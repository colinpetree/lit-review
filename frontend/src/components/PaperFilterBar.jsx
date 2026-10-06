import { useEffect, useRef, useState } from 'react'
import {
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  Book,
  BookOpen,
  BookOpenCheck,
  CalendarArrowDown,
  CalendarArrowUp,
  CircleSlash2,
  Search,
  SlidersHorizontal,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react'
import Combobox from './Combobox'
import { EMPTY_PAPER_FILTER, PAPER_SORT_OPTIONS, isPaperFilterActive } from '../lib/paperFilter'

const digitsOnly = (value) => value.replace(/\D/g, '')

const READ_OPTIONS = [
  { value: 'all', label: 'All', icon: Book },
  { value: 'unread', label: 'Unread', icon: BookOpen },
  { value: 'read', label: 'Read', icon: BookOpenCheck },
]
const RELEVANCE_OPTIONS = [
  { value: 'all', label: 'All', icon: Book },
  { value: 'relevant', label: 'Relevant', icon: ThumbsUp },
  { value: 'neutral', label: 'Neutral', icon: CircleSlash2 },
  { value: 'not_relevant', label: 'Not Relevant', icon: ThumbsDown },
]

// asPlaceholder: clicking lists every sort instead of editing the current label.
const SORT_ICONS = {
  'date-desc': CalendarArrowDown,
  'date-asc': CalendarArrowUp,
  'citations-desc': ArrowDownWideNarrow,
  'citations-asc': ArrowUpNarrowWide,
}
const SORT_OPTIONS = PAPER_SORT_OPTIONS.map((o) => ({ ...o, icon: SORT_ICONS[o.value], asPlaceholder: true }))

// Search box (filters on every keystroke), a popover of extra filters and,
// when onSortChange is given, a sort picker. shown/total are the filtered and
// unfiltered paper counts, used for the "Showing X of Y" line while a filter
// is active. showRelevance (run results only) adds the relevance filter.
export default function PaperFilterBar({
  filter,
  onChange,
  shown,
  total,
  sort,
  onSortChange,
  showRelevance,
  showNew,
}) {
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
            className="w-full rounded-md border border-gray-300 py-2 pl-9 pr-8 text-sm text-gray-800"
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
            className={`relative flex items-center gap-1.5 rounded-md border bg-surface px-3 py-2 text-sm hover:bg-gray-100 ${
              active ? 'border-blue-300 text-blue-700 dark:border-blue-700 dark:text-blue-300' : 'pick-button border-gray-300 text-gray-600'
            }`}
          >
            <SlidersHorizontal size={14} />
            Filters
            {active ? (
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-blue-600" />
            ) : null}
          </button>
          {open ? (
            <div className="absolute right-0 z-10 mt-1 w-72 rounded-md border border-gray-200 bg-surface p-3 shadow-lg">
              <div className="text-sm text-gray-700">
                <span className="mb-1 block">Read status</span>
                <Combobox
                  options={READ_OPTIONS}
                  value={filter.readState}
                  onChange={(readState) => onChange({ ...filter, readState })}
                  placeholder="All"
                  searchable={false}
                />
              </div>
              {showRelevance ? (
                <div className="mt-3 text-sm text-gray-700">
                  <span className="mb-1 block">Relevance</span>
                  <Combobox
                    options={RELEVANCE_OPTIONS}
                    value={filter.relevance}
                    onChange={(relevance) => onChange({ ...filter, relevance })}
                    placeholder="All"
                    searchable={false}
                  />
                </div>
              ) : null}
              {showNew ? (
                <div className="mt-3 flex items-center justify-between gap-3 border-t border-gray-100 pt-3 text-sm text-gray-700">
                  <span id="new-papers-label">New in the latest check</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={filter.newOnly}
                    aria-labelledby="new-papers-label"
                    onClick={() => onChange({ ...filter, newOnly: !filter.newOnly })}
                    className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                      filter.newOnly ? 'bg-blue-600' : 'bg-gray-300'
                    }`}
                  >
                    <span
                      className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        filter.newOnly ? 'translate-x-4' : ''
                      }`}
                    />
                  </button>
                </div>
              ) : null}
              <div className="mt-3 flex items-center justify-between gap-3 border-t border-gray-100 pt-3 text-sm text-gray-700">
                <span id="hide-retracted-label">Hide retracted papers</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={filter.hideRetracted}
                  aria-labelledby="hide-retracted-label"
                  onClick={() => onChange({ ...filter, hideRetracted: !filter.hideRetracted })}
                  className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
                    filter.hideRetracted ? 'bg-blue-600' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                      filter.hideRetracted ? 'translate-x-4' : ''
                    }`}
                  />
                </button>
              </div>
              <div className="mt-3 flex items-center justify-between gap-3 border-t border-gray-100 pt-3 text-sm text-gray-700">
                <span id="missing-abstract-label">Papers missing abstracts</span>
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
              <div className="mt-3 border-t border-gray-100 pt-3 text-sm text-gray-700">
                <span className="block">Publication year</span>
                <div className="mt-1 flex items-center gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    aria-label="From year"
                    placeholder="From"
                    value={filter.yearFrom}
                    onChange={(e) => onChange({ ...filter, yearFrom: digitsOnly(e.target.value) })}
                    className="w-full rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-800"
                  />
                  <span className="text-gray-400">to</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    aria-label="To year"
                    placeholder="To"
                    value={filter.yearTo}
                    onChange={(e) => onChange({ ...filter, yearTo: digitsOnly(e.target.value) })}
                    className="w-full rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-800"
                  />
                </div>
              </div>
              <label className="mt-3 block text-sm text-gray-700">
                Minimum citations
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="0"
                  value={filter.minCitations}
                  onChange={(e) => onChange({ ...filter, minCitations: digitsOnly(e.target.value) })}
                  className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-800"
                />
              </label>
            </div>
          ) : null}
        </div>

        {onSortChange ? (
          <div className="w-40 shrink-0">
            <Combobox options={SORT_OPTIONS} value={sort} onChange={onSortChange} placeholder="Sort by" subtle searchable={false} />
          </div>
        ) : null}
      </div>

      {active ? (
        <p className="mt-2 text-sm text-gray-500">
          Showing {shown} of {total} papers ·{' '}
          <button
            type="button"
            onClick={() => onChange(EMPTY_PAPER_FILTER)}
            className="text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
          >
            Clear filters
          </button>
        </p>
      ) : null}
    </div>
  )
}
