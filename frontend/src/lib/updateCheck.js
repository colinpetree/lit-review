import { useCallback, useEffect, useState } from 'react'
import { fetchJson } from './api'
import { isHttpUrl } from './format'

// Whether the page asks GitHub (through the app) if a newer Lit Review has been
// published, and which announcement the user has already dismissed. Both are kept
// per browser in localStorage, which can be missing or throw (private window,
// blocked site data), so every access is guarded: the check then stays on and a
// dismissed notice just comes back after a reload.
const ENABLED_KEY = 'lit-review.update-check'
const DISMISSED_KEY = 'lit-review.update-dismissed'

export function getUpdateCheckEnabled() {
  try {
    return localStorage.getItem(ENABLED_KEY) !== 'false'
  } catch {
    return true
  }
}

export function getDismissedVersion() {
  try {
    return localStorage.getItem(DISMISSED_KEY)
  } catch {
    return null
  }
}

function rememberDismissed(version) {
  try {
    localStorage.setItem(DISMISSED_KEY, version)
  } catch {
    // Storage unavailable: it is dismissed until the page reloads.
  }
}

// Current choice plus a setter, kept in step with other tabs.
export function useUpdateCheckEnabled() {
  const [enabled, setEnabledState] = useState(getUpdateCheckEnabled)

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === ENABLED_KEY) setEnabledState(getUpdateCheckEnabled())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const choose = (next) => {
    setEnabledState(next)
    try {
      localStorage.setItem(ENABLED_KEY, String(next))
    } catch {
      // Storage unavailable: the choice still applies until reload.
    }
  }
  return [enabled, choose]
}

// Show the notice only for a newer release with a link we can open, and not again
// once the user has dismissed that very version (a later release shows again).
export function shouldShowUpdate(info, dismissedVersion) {
  return Boolean(
    info && info.newer === true && typeof info.latest === 'string' && isHttpUrl(info.url) && info.latest !== dismissedVersion,
  )
}

// The release to tell the user about, or null. Asks once when the page loads and
// not at all when the user switched the check off; any failure is just "nothing new".
export function useUpdateNotice() {
  const [info, setInfo] = useState(null)
  const [dismissed, setDismissed] = useState(getDismissedVersion)

  useEffect(() => {
    if (!getUpdateCheckEnabled()) return undefined
    let cancelled = false
    fetchJson('/api/update-check')
      .then((data) => {
        if (!cancelled) setInfo(data)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const dismiss = useCallback(() => {
    if (info?.latest) {
      rememberDismissed(info.latest)
      setDismissed(info.latest)
    }
  }, [info])

  return { notice: shouldShowUpdate(info, dismissed) ? info : null, dismiss }
}
