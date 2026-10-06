import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchJson, postJson, putJson } from './api'
import { isHttpUrl } from './format'

// What the page knows about updates comes from the app, which checks GitHub on its own in the
// background (it always does, and downloads a newer signed version when there is one). The page
// only shows where that stands and lets the user choose when to install. Only the dismissal of a
// notice is kept in this browser, in localStorage, which can be missing or throw (private window,
// blocked site data), so every access is guarded: a dismissed notice just comes back after a reload.
const DISMISSED_KEY = 'lit-review.update-dismissed'

export const POLL_FAST_MS = 2500 // while something is happening
export const POLL_SLOW_MS = 60 * 1000 // a cheap local request: how late the "update ready" dialog can be

export function getDismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY)
  } catch {
    return null
  }
}

export function rememberDismissed(key) {
  try {
    localStorage.setItem(DISMISSED_KEY, key)
  } catch {
    // Storage unavailable: it is dismissed until the page reloads.
  }
}

// Which notice to show for the app's update status, or null. `kind` says what it is:
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
  if (state === 'downloading') return { ...base, kind: 'downloading', progress: Number(status.progress) || 0, dismissible: true }
  if (state === 'staged') return { ...base, kind: installsAtNextStart(status) ? 'ready-auto' : 'ready', dismissible: true }
  if (state === 'failed' || state === 'unsupported') return { ...base, kind: 'problem', state, dismissible: true }
  return null
}

// Which notices appear at the top of the page. A download in progress and a finished one waiting to be
// installed do not: the download is quiet (Settings shows its progress), and the "update ready" dialog
// announces that it is done. That is true of an update an old version needs too: it is handled the same
// way and worded just as calmly. What stays is what needs the person's attention: a failure and the restart.
const QUIET_KINDS = ['downloading', 'ready', 'ready-auto']
export function isBannerNotice(notice) {
  return Boolean(notice && !QUIET_KINDS.includes(notice.kind))
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
  if (!status) return POLL_SLOW_MS
  // Quick while a download or restart is under way, and while the first check (a few seconds after the
  // app starts) has not finished: the download is quiet, so the page must not miss it starting.
  const waitingForFirstCheck = status.enabled !== false && status.state === 'idle' && !status.checked_at
  return ['downloading', 'applying', 'available'].includes(status.state) || waitingForFirstCheck ? POLL_FAST_MS : POLL_SLOW_MS
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

// The "update ready" dialog opens when a downloaded update is waiting (the moment a download finishes, and
// at every start that finds one waiting) for someone who installs updates themselves, or whose version is
// too old to keep. It is not shown to someone whose updates install on their own at the next start. The key is one run of the
// app plus one version, so closing it silences it until the app is next started or a newer version arrives.
export function modalKey(status) {
  return status && status.instance && status.latest ? `${status.instance}:${status.latest}` : null
}

// An update that installs on its own at the next start: the person chose automatic installing, or the
// running version is too old to keep (the release says so). Either way they can still install it now.
export function installsAtNextStart(status) {
  return Boolean(status && (status.auto_apply === true || status.required === true))
}

export function shouldOfferModal(status, dismissedKey) {
  // Someone who chose automatic installing is not interrupted, unless their version is too old to keep.
  if (!status || status.state !== 'staged' || (status.auto_apply === true && status.required !== true)) return false
  const key = modalKey(status)
  return key !== null && key !== dismissedKey
}

// The dialog's dismissal lives in sessionStorage (this tab, kept over a reload), which can be missing
// or throw, so every access is guarded: the dialog then simply comes back after a reload.
const MODAL_DISMISSED_KEY = 'lit-review.update-modal-dismissed'

export function getModalDismissed() {
  try {
    return sessionStorage.getItem(MODAL_DISMISSED_KEY)
  } catch {
    return null
  }
}

export function rememberModalDismissed(key) {
  try {
    sessionStorage.setItem(MODAL_DISMISSED_KEY, key)
  } catch {
    // Storage unavailable: it is dismissed until the page reloads.
  }
}

// Ask the app to install what is downloaded and restart. The app finishes what it is doing first,
// and answers 409 (with a message) if it cannot within a moment.
export function installUpdate() {
  return postJson('/api/update/apply', {})
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
      if (status.error) return `Could not check: ${status.error}`
      // Nothing has been asked yet (the first check runs a few seconds after the app starts): not "up to date".
      if (status.enabled === false) return 'Updates are only checked in the installed app'
      if (!status.checked_at) return 'Checking for a new version...'
      return 'You have the latest version'
  }
}
