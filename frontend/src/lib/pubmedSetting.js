import { useEffect, useState } from 'react'

// Whether PubMed is offered as a paper source on Discover Papers. On by default;
// people outside medicine and health can switch it off in Settings. Kept per
// browser in localStorage, which can be missing or throw (private window,
// blocked site data), so every access is guarded and PubMed just stays on.
const KEY = 'lit-review.pubmed-enabled'

export function getPubMedEnabled() {
  try {
    return localStorage.getItem(KEY) !== 'false'
  } catch {
    return true
  }
}

// Current choice plus a setter, kept in step with other tabs.
export function usePubMedEnabled() {
  const [enabled, setEnabledState] = useState(getPubMedEnabled)

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === KEY) setEnabledState(getPubMedEnabled())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const choose = (next) => {
    setEnabledState(next)
    try {
      localStorage.setItem(KEY, String(next))
    } catch {
      // Storage unavailable: the choice still applies until reload.
    }
  }
  return [enabled, choose]
}
