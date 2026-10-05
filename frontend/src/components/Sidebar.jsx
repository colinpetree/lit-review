import { Link, NavLink } from 'react-router-dom'
import { GraduationCap } from 'lucide-react'
import { NAV_ITEMS, SETTINGS_ITEM } from '../lib/navItems'
import { useSettingsModal } from './SettingsModalProvider'
import { Tooltip } from './ui/Tooltip'
import useCollapsedNav from '../lib/useCollapsedNav'

const linkClass = ({ isActive }) =>
  `flex h-9 w-9 mx-auto items-center justify-center gap-2.5 rounded-md text-sm lg:h-auto lg:w-full lg:justify-start lg:px-3 lg:py-2 transition-colors ${
    isActive ? 'bg-stone-200 text-stone-700 font-medium' : 'text-stone-500 hover:text-stone-700 hover:bg-stone-200/60'
  }`

export default function Sidebar() {
  const { openSettings } = useSettingsModal()
  const collapsed = useCollapsedNav()
  // Names show as tooltips only while the labels are hidden.
  const tip = (label) => (collapsed ? label : null)

  return (
    <aside className="flex w-14 shrink-0 flex-col border-r border-stone-200 bg-sidebar lg:w-56">
      <div className="border-b border-stone-200 px-2 py-4 lg:px-3">
        <Tooltip content={tip('Lit Review')} side="right">
          <Link
            to="/"
            aria-label="Lit Review"
            className="flex cursor-pointer items-center justify-center gap-2.5 text-sm font-semibold text-stone-700 lg:justify-start lg:px-3"
          >
            <GraduationCap size={18} />
            <span className="hidden lg:inline">Lit Review</span>
          </Link>
        </Tooltip>
      </div>
      <nav className="mt-3 flex-1 overflow-y-auto overflow-x-hidden px-2 space-y-1 lg:px-3">
        {NAV_ITEMS.map((item) => (
          <Tooltip key={item.to} content={tip(item.label)} side="right">
            {/* The wrapper takes the tooltip's props: Radix can't merge them into NavLink's function className. */}
            <div>
              <NavLink to={item.to} aria-label={item.label} className={linkClass}>
                <item.icon size={16} className="shrink-0" />
                <span className="hidden lg:inline">{item.label}</span>
              </NavLink>
            </div>
          </Tooltip>
        ))}
      </nav>
      <div className="shrink-0 px-2 pb-3 lg:px-3">
        {/* Settings is a dialog over the app, not a page, so this is a button. */}
        <Tooltip content={tip(SETTINGS_ITEM.label)} side="right">
          <button
            type="button"
            aria-label={SETTINGS_ITEM.label}
            onClick={() => openSettings()}
            className={`${linkClass({ isActive: false })} lg:text-left`}
          >
            <SETTINGS_ITEM.icon size={16} className="shrink-0" />
            <span className="hidden lg:inline">{SETTINGS_ITEM.label}</span>
          </button>
        </Tooltip>
      </div>
    </aside>
  )
}
