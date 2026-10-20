import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronRight, MoreHorizontal } from 'lucide-react'

const FLYOUT_WIDTH = 176 // matches the flyout's w-44

const itemClass = (danger) =>
  `flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 ${danger ? 'text-red-600 dark:text-red-400' : 'text-gray-700'}`

// An item that opens a flyout of choices on hover (or click, for touch and
// keyboard). The flyout opens to the right, flipping to the left when it
// would run off the screen.
function SubmenuItem({ label, icon: Icon, submenu, onPick }) {
  const [open, setOpen] = useState(false)
  const [flip, setFlip] = useState(false)
  const rowRef = useRef(null)

  const show = () => {
    const rect = rowRef.current?.getBoundingClientRect()
    setFlip(Boolean(rect) && rect.right + FLYOUT_WIDTH > window.innerWidth - 8)
    setOpen(true)
  }

  return (
    <div ref={rowRef} className="relative" onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={show}
        className={itemClass(false)}
      >
        {Icon ? <Icon size={14} /> : null}
        {label}
        <ChevronRight size={14} className="ml-auto text-gray-400" />
      </button>
      {open ? (
        <div
          role="menu"
          className={`absolute top-0 z-20 -mt-1 w-44 rounded-md border border-gray-200 bg-surface py-1 shadow-lg ${
            flip ? 'right-full' : 'left-full'
          }`}
        >
          {submenu.map((item) => (
            <MenuItem key={item.label} item={item} onPick={onPick} />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function MenuItem({ item, onPick }) {
  const { label, icon: Icon, onClick, danger, checked, submenu } = item
  if (submenu) return <SubmenuItem label={label} icon={Icon} submenu={submenu} onPick={onPick} />
  return (
    <button
      type="button"
      role={checked === undefined ? 'menuitem' : 'menuitemradio'}
      aria-checked={checked}
      onClick={() => {
        onPick()
        onClick()
      }}
      className={itemClass(danger)}
    >
      {Icon ? <Icon size={14} /> : null}
      {label}
      {checked ? <Check size={14} className="ml-auto text-blue-600 dark:text-blue-400" /> : null}
    </button>
  )
}

const MENU_GAP = 4 // px between the button and the popover, as mt-1
const SCREEN_MARGIN = 8

// A "more" (horizontal dots) button that opens a popover of actions.
// items: [{ label, icon: LucideIcon, onClick, danger, checked, submenu }]. A
// boolean `checked` makes the item a radio-style choice with a checkmark when
// true. `submenu` (an array of the same items, no nesting beyond one level)
// replaces onClick with a chevron and a flyout. The position class
// comes from the caller (e.g. "absolute right-5 top-5"); the popover anchors
// to this wrapper, so it must be positioned.
// floating: draw the popover over the page (fixed, in document.body) instead of inside the
// wrapper, for a menu inside a box that scrolls or clips (a table row): it opens below the
// button, or above it when there is no room below, and closes on any scroll or resize.
export default function MoreMenu({ items, className = 'relative', floating = false }) {
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState(null)
  const ref = useRef(null)
  const popRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => {
      const inside = ref.current?.contains(e.target) || popRef.current?.contains(e.target)
      if (!inside) setOpen(false)
    }
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // A floating popover is placed from the button's spot on screen, so anything that moves the
  // button closes it rather than leaving it behind.
  useEffect(() => {
    if (!open || !floating) return
    const close = (e) => {
      if (!popRef.current?.contains(e.target)) setOpen(false)
    }
    const closeAll = () => setOpen(false)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', closeAll)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', closeAll)
    }
  }, [open, floating])

  // Measured before the browser paints, so the popover never shows in the wrong spot first.
  useLayoutEffect(() => {
    if (!open || !floating) return
    const button = ref.current?.getBoundingClientRect()
    const height = popRef.current?.offsetHeight ?? 0
    if (!button) return
    const right = Math.max(SCREEN_MARGIN, window.innerWidth - button.right)
    const fitsBelow = button.bottom + MENU_GAP + height <= window.innerHeight - SCREEN_MARGIN
    setPlace(
      fitsBelow
        ? { top: button.bottom + MENU_GAP, right }
        : { top: Math.max(SCREEN_MARGIN, button.top - MENU_GAP - height), right }
    )
  }, [open, floating])

  const menu = (
    <div
      ref={popRef}
      role="menu"
      style={floating ? { position: 'fixed', ...(place ?? { top: 0, right: 0 }), visibility: place ? 'visible' : 'hidden' } : undefined}
      className={`${floating ? 'z-50' : 'absolute right-0 z-10 mt-1'} w-44 rounded-md border border-gray-200 bg-surface py-1 shadow-lg`}
    >
      {items.map((item) => (
        <MenuItem key={item.label} item={item} onPick={() => setOpen(false)} />
      ))}
    </div>
  )

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
      {open ? (floating ? createPortal(menu, document.body) : menu) : null}
    </div>
  )
}
