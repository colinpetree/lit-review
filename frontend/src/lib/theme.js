import { useEffect, useState } from 'react'

// Theme choice (light / dark / system), kept per browser in localStorage and
// applied as a `dark` class on <html>. index.html runs the same check before
// first paint, so keep the two in sync.
export const THEMES = ['light', 'dark', 'system']
const KEY = 'theme'
const query = () => window.matchMedia('(prefers-color-scheme: dark)')

export function getTheme() {
  try {
    const t = localStorage.getItem(KEY)
    return THEMES.includes(t) ? t : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme = getTheme()) {
  const dark = theme === 'dark' || (theme === 'system' && query().matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function setTheme(theme) {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // Storage unavailable: the choice still applies until reload.
  }
  applyTheme(theme)
}

// Current choice plus a setter. Follows OS changes while on System, and other
// tabs changing the choice.
export function useTheme() {
  const [theme, setThemeState] = useState(getTheme)

  useEffect(() => {
    const mq = query()
    const onOsChange = () => applyTheme(theme)
    const onStorage = (e) => {
      if (e.key !== KEY) return
      const next = getTheme()
      setThemeState(next)
      applyTheme(next)
    }
    mq.addEventListener('change', onOsChange)
    window.addEventListener('storage', onStorage)
    return () => {
      mq.removeEventListener('change', onOsChange)
      window.removeEventListener('storage', onStorage)
    }
  }, [theme])

  const choose = (next) => {
    setThemeState(next)
    setTheme(next)
  }
  return [theme, choose]
}
