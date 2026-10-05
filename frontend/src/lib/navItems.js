import { Bot, ChartColumn, Database, FlaskConical, HardDrive, Info, Library, ListChecks, Palette, Scale, Search, Settings } from 'lucide-react'

// Single source of truth for the side nav and for the icon shown beside each
// top-level page title.
export const NAV_ITEMS = [
  { to: '/discover', label: 'Discover Papers', icon: Search },
  { to: '/datasets', label: 'Paper Datasets', icon: Database },
  { to: '/prompts', label: 'Grading Prompts', icon: ListChecks },
  { to: '/evaluate', label: 'Evaluate Papers', icon: FlaskConical },
  { to: '/results', label: 'Results', icon: ChartColumn },
]

// The button at the bottom of the main sidebar. It opens the settings modal.
export const SETTINGS_ITEM = { label: 'Settings', icon: Settings }

// The sections of the settings modal, top to bottom (the id is also what openSettings takes
// and the end of each section's element id). API keys come first because a new user needs them first.
export const SETTINGS_NAV = [
  { id: 'ai', label: 'AI Integrations', icon: Bot },
  { id: 'databases', label: 'Research Databases', icon: Library },
  { id: 'data', label: 'Your Data', icon: HardDrive },
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'about', label: 'Software and Updates', icon: Info },
  { id: 'license', label: 'License and Notices', icon: Scale },
]

export const navIcon = (to) => NAV_ITEMS.find((item) => item.to === to)?.icon
