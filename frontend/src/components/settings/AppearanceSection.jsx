import { Monitor, Moon, Sun } from 'lucide-react'
import SettingsPanel from './SettingsPanel'
import { useTheme } from '../../lib/theme'
import Combobox from '../Combobox'
import SettingsSection from './SettingsSection'

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

export default function AppearanceSection() {
  const [theme, setTheme] = useTheme()

  return (
    <SettingsPanel
      title="Appearance"
      id="appearance"
      description="Choose light, dark, or match your computer. Saved in this browser."
    >
      <SettingsSection title="Theme">
        <div className="max-w-xs">
          <Combobox options={THEME_OPTIONS} value={theme} onChange={setTheme} placeholder="Theme" />
        </div>
      </SettingsSection>
    </SettingsPanel>
  )
}
