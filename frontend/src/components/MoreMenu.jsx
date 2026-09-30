import { useEffect, useRef, useState } from 'react'
import { MoreHorizontal } from 'lucide-react'

// A "more" (horizontal dots) button that opens a popover of actions.
// items: [{ label, icon: LucideIcon, onClick, danger }]. The position class
// comes from the caller (e.g. "absolute right-5 top-5"); the popover anchors
// to this wrapper, so it must be positioned.
export default function MoreMenu({ items, className = 'relative' }) {
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
    <div ref={ref} className={className}>
      <button
        type="button"
        aria-label="More actions"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
      >
        <MoreHorizontal size={18} />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 z-10 mt-1 w-44 rounded-md border border-gray-200 bg-white py-1 shadow-lg"
        >
          {items.map(({ label, icon: Icon, onClick, danger }) => (
            <button
              key={label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false)
                onClick()
              }}
              className={`flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 ${
                danger ? 'text-red-600' : 'text-gray-700'
              }`}
            >
              {Icon ? <Icon size={14} /> : null}
              {label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
