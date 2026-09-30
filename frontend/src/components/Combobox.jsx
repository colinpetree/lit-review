import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

// Type-to-filter dropdown used for every picker in the app.
//
// options: [{ value, label, group?, pinned?, emphasis?, asPlaceholder? }]
//   group         optional heading; shown only when there is more than one group
//   pinned        stays in the list while filtering (e.g. "New prompt")
//   emphasis      styles the option blue/medium
//   asPlaceholder when selected, the label is shown as placeholder text and the
//                 field reads as empty, so clicking lists everything and typing
//                 filters from scratch instead of editing the label
// value: the selected option's value, or null/undefined for none.
export default function Combobox({ options, value, onChange, placeholder, emptyText = 'No matches.' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(0)
  const ref = useRef(null)
  const listRef = useRef(null)

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return options.filter((o) => o.pinned || !q || o.label.toLowerCase().includes(q))
  }, [options, query])

  const selected = options.find((o) => o.value === value)
  const showGroups = new Set(options.map((o) => o.group).filter(Boolean)).size > 1

  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // Keep the highlighted row visible when arrowing through a long list.
  useEffect(() => {
    if (open) listRef.current?.children[highlight]?.scrollIntoView({ block: 'nearest' })
  }, [open, highlight])

  const openFresh = () => {
    if (open) return
    setQuery('')
    setHighlight(Math.max(0, options.findIndex((o) => o.value === value)))
    setOpen(true)
  }

  const choose = (option) => {
    onChange(option.value)
    setOpen(false)
    setQuery('')
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) openFresh()
      else setHighlight((h) => Math.min(h + 1, visible.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((h) => Math.max(h - 1, 0))
    } else if (e.key === 'Enter') {
      // Never let Enter submit the surrounding form (that would start a paid
      // run or search): with the list open it picks the highlighted option,
      // and with it closed it just reopens the list.
      e.preventDefault()
      if (!open) openFresh()
      else if (visible[highlight]) choose(visible[highlight])
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation()
      setOpen(false)
    }
  }

  const inputValue = open ? query : selected && !selected.asPlaceholder ? selected.label : ''
  const shownPlaceholder = selected ? selected.label : placeholder
  const darkPlaceholder = selected && (selected.asPlaceholder || open)

  return (
    <div ref={ref} className="relative">
      <input
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        value={inputValue}
        placeholder={shownPlaceholder}
        // The input stays focused after a choice, so onFocus alone would not
        // reopen the list on a second click.
        onFocus={openFresh}
        onClick={openFresh}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
          setHighlight(0)
        }}
        onKeyDown={onKeyDown}
        // Tabbing (or clicking) away closes the list. Option and scrollbar
        // mousedowns are prevented below, so they never blur the input.
        onBlur={() => setOpen(false)}
        className={`w-full rounded-md border border-gray-300 py-2 pl-3 pr-9 text-sm ${
          darkPlaceholder ? 'placeholder:text-gray-700' : ''
        }`}
      />
      <ChevronDown size={16} className="pointer-events-none absolute right-3 top-3 text-gray-400" />
      {open ? (
        <ul
          ref={listRef}
          role="listbox"
          onMouseDown={(e) => e.preventDefault()}
          className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-md border border-gray-200 bg-white py-1 shadow-lg"
        >
          {visible.map((option, i) => (
            <li
              key={option.value}
              role="option"
              aria-selected={option.value === value}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(option)}
              onMouseEnter={() => setHighlight(i)}
              className={`cursor-pointer px-3 py-2 text-sm ${i === highlight ? 'bg-gray-100' : ''} ${
                option.emphasis ? 'font-medium text-blue-600' : 'text-gray-700'
              }`}
            >
              {showGroups && option.group && option.group !== visible[i - 1]?.group ? (
                <span className="mb-1 block text-xs uppercase text-gray-400">{option.group}</span>
              ) : null}
              {option.label}
            </li>
          ))}
          {visible.every((o) => o.pinned) && query.trim() ? (
            <li className="px-3 py-2 text-sm text-gray-400">{emptyText}</li>
          ) : null}
        </ul>
      ) : null}
    </div>
  )
}
