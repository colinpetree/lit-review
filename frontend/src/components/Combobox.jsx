import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

// Type-to-filter dropdown used for every picker in the app.
//
// options: [{ value, label, group?, icon?, hint?, hintTitle?, pinned?, emphasis?, asPlaceholder? }]
//   icon          optional lucide component shown before the label in the list
//   hint          optional faded text right-aligned in the list row (e.g. "$$");
//                 hintTitle is its hover text
//   suffix        optional faded text right after the label (e.g. a paper count)
//   detail        optional faded second line under the label (clamped to one line)
//   keywords      optional extra text the typed filter also searches (not shown)
//   group         optional heading; shown only when there is more than one group
//   pinned        stays in the list while filtering (e.g. "New prompt")
//   emphasis      styles the option blue/medium
//   asPlaceholder when selected, the label is shown as placeholder text and the
//                 field reads as empty, so clicking lists everything and typing
//                 filters from scratch instead of editing the label
// value: the selected option's value, or null/undefined for none.
// subtle: a shade lighter gray for the text and icons, for secondary controls.
// blurOnChoose: take focus out of the field after a choice (for multi-select
//   pickers, where the field stays empty and the cursor would just sit there).
export default function Combobox({
  options,
  value,
  onChange,
  placeholder,
  emptyText = 'No matches.',
  subtle = false,
  blurOnChoose = false,
}) {
  const inputRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [highlight, setHighlight] = useState(0)
  const ref = useRef(null)
  const listRef = useRef(null)

  const visible = useMemo(() => {
    // Every word typed must appear somewhere in the option's label, group
    // heading or keywords (case-insensitive), in any order.
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    return options.filter((o) => {
      if (o.pinned || !words.length) return true
      const text = [o.label, o.group, o.keywords].filter(Boolean).join(' ').toLowerCase()
      return words.every((w) => text.includes(w))
    })
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
    if (blurOnChoose) inputRef.current?.blur()
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
        ref={inputRef}
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
        className={`w-full rounded-md border border-gray-300 py-2 pr-9 text-sm ${
          // With an icon, the text sits 1px lower so it lines up with it (same height overall).
          selected?.icon ? 'pl-9 pb-[7px] pt-[9px]' : 'pl-3'
        } ${subtle ? 'text-gray-600' : ''} ${
          darkPlaceholder ? (subtle ? 'placeholder:text-gray-600' : 'placeholder:text-gray-700') : ''
        }`}
      />
      {selected?.icon ? (
        <selected.icon
          size={14}
          className={`pointer-events-none absolute left-3 top-3 ${subtle ? 'text-gray-600' : 'text-gray-700'}`}
        />
      ) : null}
      <ChevronDown size={16} className="pointer-events-none absolute right-3 top-3 text-gray-400" />
      {open ? (
        <ul
          ref={listRef}
          role="listbox"
          onMouseDown={(e) => e.preventDefault()}
          className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-md border border-gray-200 bg-surface py-1 shadow-lg"
        >
          {visible.map((option, i) => {
            const showHeading = showGroups && option.group && option.group !== visible[i - 1]?.group
            return (
              <li
                key={option.value}
                role="option"
                aria-selected={option.value === value}
                onMouseDown={(e) => e.preventDefault()}
                className={`text-sm ${
                  option.emphasis ? 'font-medium text-blue-600 dark:text-blue-400' : subtle ? 'text-gray-600' : 'text-gray-700'
                }`}
              >
                {/* The group heading sits outside the clickable, highlighted row, so
                    hovering or arrowing onto the first option never highlights it. */}
                {showHeading ? (
                  <span className="block px-3 pb-1 pt-2 text-xs font-normal uppercase text-gray-400">
                    {option.group}
                  </span>
                ) : null}
                <div
                  onClick={() => choose(option)}
                  onMouseEnter={() => setHighlight(i)}
                  className={`cursor-pointer px-3 pb-2 ${showHeading ? 'pt-1' : 'pt-2'} ${
                    i === highlight ? 'bg-gray-100' : ''
                  }`}
                >
                  {option.detail || option.suffix ? (
                    <>
                      <span>
                        {option.label}
                        {option.suffix ? <span className="text-gray-400"> {option.suffix}</span> : null}
                      </span>
                      {option.detail ? (
                        <span className="block line-clamp-1 text-xs text-gray-400">{option.detail}</span>
                      ) : null}
                    </>
                  ) : option.icon || option.hint ? (
                    <span className="flex items-center gap-2">
                      {option.icon ? <option.icon size={14} className="shrink-0" /> : null}
                      {option.label}
                      {option.hint ? (
                        <span title={option.hintTitle} className="ml-auto pl-3 pr-2 text-xs text-gray-300">
                          {option.hint}
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    option.label
                  )}
                </div>
              </li>
            )
          })}
          {visible.every((o) => o.pinned) && query.trim() ? (
            <li className="px-3 py-2 text-sm text-gray-400">{emptyText}</li>
          ) : null}
        </ul>
      ) : null}
    </div>
  )
}
