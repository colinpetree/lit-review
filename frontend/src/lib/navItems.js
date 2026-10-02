import { ChartColumn, Database, FlaskConical, ListChecks, Search, Settings } from 'lucide-react'

// Single source of truth for the side nav and for the icon shown beside each
// top-level page title.
export const NAV_ITEMS = [
  { to: '/discover', label: 'Discover Papers', icon: Search },
  { to: '/datasets', label: 'Paper Datasets', icon: Database },
  { to: '/prompts', label: 'Scoring Prompts', icon: ListChecks },
  { to: '/evaluate', label: 'Evaluate Papers', icon: FlaskConical },
  { to: '/results', label: 'Results', icon: ChartColumn },
]

export const SETTINGS_ITEM = { to: '/settings', label: 'Settings', icon: Settings }

export const navIcon = (to) => [...NAV_ITEMS, SETTINGS_ITEM].find((item) => item.to === to)?.icon
