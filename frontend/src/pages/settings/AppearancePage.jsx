import { Monitor, Moon, Sun } from 'lucide-react'
import { PageShell } from '../../components/ui'
import { navIcon } from '../../lib/navItems'
import { useTheme } from '../../lib/theme'
import Combobox from '../../components/Combobox'
import SettingsSection from '../../components/settings/SettingsSection'

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

export default function AppearancePage() {
  const [theme, setTheme] = useTheme()

  return (
    <PageShell
      title="Appearance"
      icon={navIcon('/settings/appearance')}
      description="Choose light, dark, or match your computer. Saved in this browser."
    >
      <SettingsSection title="Theme">
        <div className="max-w-xs">
          <Combobox options={THEME_OPTIONS} value={theme} onChange={setTheme} placeholder="Theme" />
        </div>
      </SettingsSection>
    </PageShell>
  )
}
