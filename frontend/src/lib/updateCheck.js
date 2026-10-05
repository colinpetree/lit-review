import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJson, postJson, putJson } from './api'
import { isHttpUrl } from './format'

// What the page knows about updates comes from the app, which checks GitHub on its own in the
// background (it always does, and downloads a newer signed version when there is one). The page
// only shows where that stands and lets the user choose when to install. Only the dismissal of a
// notice is kept in this browser, in localStorage, which can be missing or throw (private window,
// blocked site data), so every access is guarded: a dismissed notice just comes back after a reload.
const DISMISSED_KEY = 'lit-review.update-dismissed'

export const POLL_FAST_MS = 2500 // while downloading or restarting
export const POLL_SLOW_MS = 5 * 60 * 1000

export function getDismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY)
  } catch {
    return null
  }
}

function rememberDismissed(key) {
  try {
    localStorage.setItem(DISMISSED_KEY, key)
  } catch {
    // Storage unavailable: it is dismissed until the page reloads.
  }
}

// Which notice to show for the app's update status, or null. `kind` says what it is:
//   required     an old version that can no longer be relied on: cannot be dismissed
//   downloading  a newer version is being fetched
//   ready        downloaded, waiting for the user to install it
//   ready-auto   downloaded, and installs itself the next time the app is opened
//   applying     the app is restarting to install it
//   problem      it could not be fetched or installed (with a link to download it by hand)
export function updateNotice(status) {
  if (!status || typeof status.latest !== 'string' || !status.latest) return null
  const link = isHttpUrl(status.url) ? status.url : null
  const base = { latest: status.latest, current: status.current, link, text: status.notice || '', error: status.error || '' }
  const state = status.state
  if (state === 'applying') return { ...base, kind: 'applying', dismissible: false }
  if (status.required === true && ['available', 'downloading', 'staged', 'failed', 'unsupported'].includes(state)) {
    return { ...base, kind: 'required', state, dismissible: false }
  }
  if (state === 'downloading') return { ...base, kind: 'downloading', progress: Number(status.progress) || 0, dismissible: true }
  if (state === 'staged') return { ...base, kind: status.auto_apply ? 'ready-auto' : 'ready', dismissible: true }
  if (state === 'failed' || state === 'unsupported') return { ...base, kind: 'problem', state, dismissible: true }
  return null
}

// A dismissal is for one version in one kind of notice, so "downloading" going away does not hide
// "ready" later, and a newer version shows again.
export function dismissalKey(notice) {
  return `${notice.latest}:${notice.kind}`
}

export function shouldShow(notice, dismissed) {
  return Boolean(notice && (!notice.dismissible || dismissalKey(notice) !== dismissed))
}

export function pollDelay(status) {
  return status && ['downloading', 'applying'].includes(status.state) ? POLL_FAST_MS : POLL_SLOW_MS
}

// The app's update status, kept fresh (quickly while something is happening). Any failure to reach the
// app keeps the last answer: during a restart the app is briefly unreachable, and that is expected.
export function useUpdateStatus() {
  const [status, setStatus] = useState(null)
  const timer = useRef(null)
  const alive = useRef(true)

  const refresh = useCallback(async function poll() {
    clearTimeout(timer.current)
    let next = null
    try {
      next = await fetchJson('/api/update-check')
      if (alive.current) setStatus(next)
    } catch {
      // keep the last answer
    }
    if (alive.current) timer.current = setTimeout(poll, pollDelay(next))
    return next
  }, [])

  useEffect(() => {
    alive.current = true
    refresh()
    return () => {
      alive.current = false
      clearTimeout(timer.current)
    }
  }, [refresh])

  return { status, refresh, setStatus }
}

export function useUpdateNotice() {
  const { status, refresh, setStatus } = useUpdateStatus()
  const [dismissed, setDismissed] = useState(getDismissed)
  const notice = updateNotice(status)

  const dismiss = useCallback(() => {
    if (notice && notice.dismissible) {
      rememberDismissed(dismissalKey(notice))
      setDismissed(dismissalKey(notice))
    }
  }, [notice])

  // Ask the app to install what is downloaded and restart. The app finishes what it is doing first.
  const install = useCallback(async () => {
    await postJson('/api/update/apply', {})
    setStatus((current) => ({ ...current, state: 'applying' }))
    setTimeout(refresh, POLL_FAST_MS)
  }, [refresh, setStatus])

  return { notice: shouldShow(notice, dismissed) ? notice : null, dismiss, install }
}

export function fetchUpdateSettings() {
  return fetchJson('/api/settings/updates')
}

export function saveAutoApply(autoApply) {
  return putJson('/api/settings/updates', { auto_apply: autoApply })
}

export function checkNow() {
  return postJson('/api/update/check', {})
}

// One line for the Settings card.
export function describeStatus(status) {
  if (!status) return 'Checking...'
  switch (status.state) {
    case 'downloading':
      return `Downloading version ${status.latest} (${Math.round((Number(status.progress) || 0) * 100)}%)`
    case 'staged':
      return status.auto_apply
        ? `Version ${status.latest} is downloaded and installs the next time you open Lit Review`
        : `Version ${status.latest} is downloaded and ready to install`
    case 'applying':
      return `Installing version ${status.latest}...`
    case 'failed':
      return status.error || `Version ${status.latest} could not be installed`
    case 'unsupported':
      return status.error || 'This copy cannot update itself'
    case 'available':
      return status.error ? `Version ${status.latest} is available (${status.error})` : `Version ${status.latest} is available`
    default:
      return status.error ? `Could not check: ${status.error}` : 'You have the latest version'
  }
}
