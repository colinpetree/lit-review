import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/discover', label: 'Discover Papers' },
  { to: '/datasets', label: 'Paper Data Sets' },
  { to: '/analyze', label: 'Analyze Papers' },
  { to: '/prompts', label: 'Scoring Prompts' },
  { to: '/results', label: 'Past Results' },
]

const linkClass = ({ isActive }) =>
  `block px-3 py-2 rounded-md text-sm transition-colors ${
    isActive ? 'bg-gray-700 text-white font-medium' : 'text-gray-400 hover:text-white hover:bg-gray-800'
  }`

export default function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col bg-gray-900">
      <div className="px-3 py-4">
        <span className="px-3 text-sm font-semibold text-white">Lit Review Assistant</span>
      </div>
      <nav className="flex-1 overflow-auto px-3 space-y-1">
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} className={linkClass}>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="shrink-0 border-t border-gray-700 px-3 py-3">
        <NavLink to="/settings" className={linkClass}>
          Settings
        </NavLink>
      </div>
    </aside>
  )
}
