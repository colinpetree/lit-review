import { Bot, ChartColumn, Database, FlaskConical, HardDrive, Info, Library, ListChecks, Palette, Scale, Search, Settings } from 'lucide-react'

// Single source of truth for the side nav and for the icon shown beside each
// top-level page title.
export const NAV_ITEMS = [
  { to: '/discover', label: 'Discover Papers', icon: Search },
  { to: '/datasets', label: 'Paper Datasets', icon: Database },
  { to: '/prompts', label: 'Scoring Prompts', icon: ListChecks },
  { to: '/evaluate', label: 'Evaluate Papers', icon: FlaskConical },
  { to: '/results', label: 'Results', icon: ChartColumn },
]

// The button at the bottom of the main sidebar. It opens SETTINGS_NAV[0].
export const SETTINGS_ITEM = { to: '/settings', label: 'Settings', icon: Settings }

// The settings sidebar, top to bottom. API keys come first because a new user needs them first.
export const SETTINGS_NAV = [
  { to: '/settings/ai', label: 'AI Integrations', icon: Bot },
  { to: '/settings/databases', label: 'Research Databases', icon: Library },
  { to: '/settings/data', label: 'Your Data', icon: HardDrive },
  { to: '/settings/appearance', label: 'Appearance', icon: Palette },
  { to: '/settings/about', label: 'About and Updates', icon: Info },
  { to: '/settings/license', label: 'License and Notices', icon: Scale },
]

export const navIcon = (to) => [...NAV_ITEMS, ...SETTINGS_NAV, SETTINGS_ITEM].find((item) => item.to === to)?.icon
