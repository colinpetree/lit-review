import { useEffect, useState } from 'react'

// The amount above which Evaluate Papers asks before starting a run, and the limit
// each run gets. A number of dollars; 0 means always ask; blank means never ask (and
// no limit unless the user raises one on a run). Kept per browser in localStorage, which
// can be missing or throw (private window, blocked site data), so every access is
// guarded and the default applies.
const KEY = 'lit-review.spend-confirm-usd'
export const DEFAULT_THRESHOLD_TEXT = '1.00'

// How far above the estimate a run the user agreed to may go before it stops. An
// estimate is approximate, so a limit at exactly the estimate would stop runs that were
// on track; this leaves room, while still catching a run that costs far more.
export const LIMIT_MARGIN = 1.25

// The threshold as a number of dollars, or null for "never ask". Text that is not a
// non-negative number gives undefined, so a form can tell "blank" from "mistyped".
export function parseThreshold(text) {
  const trimmed = String(text ?? '').trim().replace(/^\$/, '')
  if (trimmed === '') return null
  if (!/^\d+(\.\d{0,2})?$/.test(trimmed) && !/^\.\d{1,2}$/.test(trimmed)) return undefined
  const value = Number(trimmed)
  return Number.isFinite(value) ? value : undefined
}

export function getSpendThresholdText() {
  try {
    const stored = localStorage.getItem(KEY)
    return stored === null ? DEFAULT_THRESHOLD_TEXT : stored
  } catch {
    return DEFAULT_THRESHOLD_TEXT
  }
}

export function getSpendThreshold() {
  const parsed = parseThreshold(getSpendThresholdText())
  // A stored value that no longer parses is treated as the default, not as "never ask".
  return parsed === undefined ? parseThreshold(DEFAULT_THRESHOLD_TEXT) : parsed
}

// Whether a run estimated at `usd` needs the user's confirmation first.
export function needsConfirmation(usd, threshold) {
  if (threshold === null || threshold === undefined) return false
  if (threshold === 0) return true
  return usd > threshold
}

// The most a new run may spend (dollars), or null for no limit. A run the user confirmed
// gets the estimate plus a margin, rounded up to the cent. One that needed no
// confirmation gets the threshold: it was expected to cost less, so reaching it means the
// estimate was wrong, and they asked to hear before spending that much.
export function limitFor({ usd, threshold, confirmed }) {
  if (confirmed) return Math.max(0.01, Math.ceil(usd * LIMIT_MARGIN * 100) / 100)
  if (threshold === null || threshold === undefined || threshold === 0) return null
  return threshold
}

// Current text plus a setter, kept in step with other tabs.
export function useSpendThresholdText() {
  const [text, setTextState] = useState(getSpendThresholdText)

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === KEY) setTextState(getSpendThresholdText())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const choose = (next) => {
    setTextState(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      // Storage unavailable: the choice still applies until reload.
    }
  }
  return [text, choose]
}

// "$0.12", "$12.40", or "under $0.01" for a tiny amount.
export function formatUsd(usd) {
  if (!Number.isFinite(usd)) return ''
  if (usd > 0 && usd < 0.01) return 'under $0.01'
  return `$${usd.toFixed(2)}`
}
