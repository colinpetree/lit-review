import { useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

// The selected tab of a detail page, kept in the address (`?tab=<id>`) so a reload or Back keeps
// it. The first tab is the default and has no parameter; an unknown value falls back to it.
export function useTab(ids) {
  const [params, setParams] = useSearchParams()
  const asked = params.get('tab')
  const value = ids.includes(asked) ? asked : ids[0]
  const setValue = (id) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (id === ids[0]) next.delete('tab')
        else next.set('tab', id)
        return next
      },
      { replace: true }
    )
  return [value, setValue]
}

const tabId = (id) => `tab-${id}`
const panelId = (id) => `tabpanel-${id}`

// A row of tabs (`tabs`: [{ id, label, count? }], where a count of null or undefined is left off,
// for one still loading). Left and Right arrows move between them.
export function Tabs({ tabs, value, onChange, className = '' }) {
  const refs = useRef({})
  const onKeyDown = (e) => {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const i = tabs.findIndex((t) => t.id === value)
    const next = tabs[(i + step + tabs.length) % tabs.length]
    onChange(next.id)
    refs.current[next.id]?.focus()
  }
  return (
    <div role="tablist" onKeyDown={onKeyDown} className={`flex gap-6 border-b border-gray-200 ${className}`}>
      {tabs.map((t) => {
        const selected = t.id === value
        return (
          <button
            key={t.id}
            ref={(node) => {
              refs.current[t.id] = node
            }}
            type="button"
            role="tab"
            id={tabId(t.id)}
            aria-selected={selected}
            aria-controls={panelId(t.id)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.id)}
            className={`-mb-px border-b-2 pb-2 text-sm font-medium transition-colors ${
              selected
                ? 'border-blue-600 text-gray-800 dark:border-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
            {t.count != null ? <span className="ml-1.5 text-gray-400">{t.count}</span> : null}
          </button>
        )
      })}
    </div>
  )
}

// The content of the selected tab.
export function TabPanel({ id, className = '', children }) {
  return (
    <div role="tabpanel" id={panelId(id)} aria-labelledby={tabId(id)} className={className}>
      {children}
    </div>
  )
}
