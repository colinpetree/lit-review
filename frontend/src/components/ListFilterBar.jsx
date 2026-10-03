import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarArrowDown, CalendarArrowUp, Search, SlidersHorizontal, X } from 'lucide-react'
import Combobox from './Combobox'
import DatePicker from './DatePicker'
import { PROVIDER_LABELS, modelName, providerIcon } from '../lib/models'
import { EMPTY_LIST_FILTER, LIST_SORT_OPTIONS, isFullDate, isListFilterActive, modelKey } from '../lib/listFilter'

const SORT_ICONS = { newest: CalendarArrowDown, oldest: CalendarArrowUp }
const SORT_OPTIONS = LIST_SORT_OPTIONS.map((o) => ({ ...o, icon: SORT_ICONS[o.value], asPlaceholder: true }))

// Search box, a popover with a created-date range (and a model picker when
// `items` carry ai_api/ai_model), and a newest/oldest sort picker. `items` is
// the full unfiltered list, used to offer only the models that actually appear
// in it. shown/total feed the "Showing X of Y" line while a filter is active.
export default function ListFilterBar({
  filter,
  onChange,
  sort,
  onSortChange,
  placeholder,
  noun,
  shown,
  total,
  items,
  showModelFilter = false,
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

  const modelOptions = useMemo(() => {
    if (!showModelFilter) return []
    const seen = new Map()
    for (const item of items ?? []) {
      if (item.ai_model) seen.set(modelKey(item.ai_api, item.ai_model), item)
    }
    const models = [...seen.entries()].map(([value, item]) => ({
      value,
      label: modelName(item.ai_api, item.ai_model),
      group: PROVIDER_LABELS[item.ai_api] || item.ai_api,
      keywords: `${item.ai_api} ${item.ai_model.split('/').pop()}`,
      icon: providerIcon(item.ai_api),
    }))
    models.sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label))
    return [{ value: '', label: 'All models', asPlaceholder: true, pinned: true }, ...models]
  }, [items, showModelFilter])

  const active = isListFilterActive(filter)
  // The search box is its own indicator, so the dot only tracks the popover.
  const popoverActive = Boolean(isFullDate(filter.dateFrom) || isFullDate(filter.dateTo) || filter.model)

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={filter.query}
            onChange={(e) => onChange({ ...filter, query: e.target.value })}
            placeholder={placeholder}
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
              popoverActive ? 'border-blue-300 text-blue-700 dark:border-blue-700 dark:text-blue-300' : 'pick-button border-gray-300 text-gray-600'
            }`}
          >
            <SlidersHorizontal size={14} />
            Filters
            {popoverActive ? (
              <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-blue-600" />
            ) : null}
          </button>
          {open ? (
            <div className="absolute right-0 z-10 mt-1 w-72 rounded-md border border-gray-200 bg-surface p-3 shadow-lg">
              <div className="text-sm text-gray-700">
                <span className="block">Created</span>
                <div className="mt-1 flex items-center gap-2">
                  <DatePicker
                    ariaLabel="Created from"
                    placeholder="From"
                    value={filter.dateFrom}
                    onChange={(dateFrom) => onChange({ ...filter, dateFrom })}
                    className="min-w-0 flex-1"
                  />
                  <span className="text-gray-400">to</span>
                  <DatePicker
                    ariaLabel="Created to"
                    placeholder="To"
                    align="right"
                    value={filter.dateTo}
                    onChange={(dateTo) => onChange({ ...filter, dateTo })}
                    className="min-w-0 flex-1"
                  />
                </div>
              </div>
              {showModelFilter ? (
                <div className="mt-3 border-t border-gray-100 pt-3 text-sm text-gray-700">
                  <span className="mb-1 block">AI model</span>
                  <Combobox
                    options={modelOptions}
                    value={filter.model}
                    onChange={(model) => onChange({ ...filter, model })}
                    placeholder="All models"
                  />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="w-40 shrink-0">
          <Combobox options={SORT_OPTIONS} value={sort} onChange={onSortChange} placeholder="Sort by" subtle searchable={false} />
        </div>
      </div>

      {active ? (
        <p className="mt-2 text-sm text-gray-500">
          Showing {shown} of {total} {noun} ·{' '}
          <button
            type="button"
            onClick={() => onChange(EMPTY_LIST_FILTER)}
            className="text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
          >
            Clear filters
          </button>
        </p>
      ) : null}
    </div>
  )
}
