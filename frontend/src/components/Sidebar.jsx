import { Link, NavLink } from 'react-router-dom'
import { GraduationCap } from 'lucide-react'
import { NAV_ITEMS, SETTINGS_ITEM } from '../lib/navItems'
import { useSettingsModal } from './SettingsModalProvider'

const linkClass = ({ isActive }) =>
  `flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
    isActive ? 'bg-stone-200 text-stone-700 font-medium' : 'text-stone-500 hover:text-stone-700 hover:bg-stone-200/60'
  }`

export default function Sidebar() {
  const { openSettings } = useSettingsModal()

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-stone-200 bg-sidebar">
      <div className="border-b border-stone-200 px-3 py-4">
        <Link to="/" className="flex cursor-pointer items-center gap-2.5 px-3 text-sm font-semibold text-stone-700">
          <GraduationCap size={18} />
          Lit Review
        </Link>
      </div>
      <nav className="mt-3 flex-1 overflow-auto px-3 space-y-1">
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} className={linkClass}>
            <item.icon size={16} />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="shrink-0 px-3 pb-3">
        {/* Settings is a dialog over the app, not a page, so this is a button. */}
        <button type="button" onClick={() => openSettings()} className={`${linkClass({ isActive: false })} w-full text-left`}>
          <SETTINGS_ITEM.icon size={16} />
          {SETTINGS_ITEM.label}
        </button>
      </div>
    </aside>
  )
}
