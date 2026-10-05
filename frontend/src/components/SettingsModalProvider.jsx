import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import SettingsModal from './SettingsModal'

const SettingsModalContext = createContext({ openSettings: () => {}, closeSettings: () => {}, settingsVersion: 0 })

// Holds whether the settings modal is open and which section it opened at. settingsVersion goes
// up each time it closes: a page that stays mounted behind it (keys, the PubMed switch) re-reads
// what Settings may have changed when that number changes.
export function SettingsModalProvider({ children }) {
  const [section, setSection] = useState(null) // a SETTINGS_NAV id, or null while closed
  const [settingsVersion, setSettingsVersion] = useState(0)
  const openSettings = useCallback((id = 'ai') => setSection(id), [])
  const closeSettings = useCallback(() => {
    setSection(null)
    setSettingsVersion((v) => v + 1)
  }, [])
  const value = useMemo(
    () => ({ openSettings, closeSettings, settingsVersion }),
    [openSettings, closeSettings, settingsVersion],
  )

  return (
    <SettingsModalContext.Provider value={value}>
      {children}
      {section ? <SettingsModal section={section} onClose={closeSettings} /> : null}
    </SettingsModalContext.Provider>
  )
}

// openSettings('databases') opens Settings at that section (the ids are in SETTINGS_NAV).
export const useSettingsModal = () => useContext(SettingsModalContext)
