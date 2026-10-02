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

// Keeps the page in step with the OS (while on System) and with other tabs
// changing the choice. Mount once at the app root so it works on every page.
export function useThemeSync() {
  useEffect(() => {
    const mq = query()
    const onOsChange = () => applyTheme()
    const onStorage = (e) => {
      if (e.key === KEY) applyTheme()
    }
    mq.addEventListener('change', onOsChange)
    window.addEventListener('storage', onStorage)
    return () => {
      mq.removeEventListener('change', onOsChange)
      window.removeEventListener('storage', onStorage)
    }
  }, [])
}

// Current choice plus a setter, for the Settings picker. The page itself is
// kept in sync by useThemeSync.
export function useTheme() {
  const [theme, setThemeState] = useState(getTheme)

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === KEY) setThemeState(getTheme())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const choose = (next) => {
    setThemeState(next)
    setTheme(next)
  }
  return [theme, choose]
}
