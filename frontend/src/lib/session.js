// The secret that lets this page use the app's API (see backend/access.py).
//
// It arrives once, in the address the app opens for the user
// (http://127.0.0.1:PORT/#token=...). The part after the # is never sent to any
// server, so it is in no request, log or Referer. The page keeps it in its own
// storage and sends it as an Authorization header on every API call.
//
// Deliberately not a cookie: a browser sends a cookie to every server on the same
// host name whatever its port, so any other web server on 127.0.0.1 could collect
// it. Page storage is kept apart per address and port, and a header is only sent
// by this page's own script, never by another site's request.

const STORAGE_KEY = 'lit-review-access'
// What a real secret looks like (the backend makes 43 URL-safe characters).
const TOKEN_FORMAT = /^[A-Za-z0-9_-]{20,200}$/

export const NOT_CONNECTED_MESSAGE =
  'This browser is not connected to Lit Review. Open Lit Review again from its icon (it opens a connected browser window) to reconnect.'

let memoryToken = null

// Storage can be missing or throw (a private window, blocked site data), so the
// secret is also held in memory for as long as the page stays open.
function readStored() {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? null
  } catch {
    return null
  }
}

function writeStored(token) {
  try {
    if (token === null) globalThis.localStorage?.removeItem(STORAGE_KEY)
    else globalThis.localStorage?.setItem(STORAGE_KEY, token)
  } catch {
    // memory still has it
  }
}

export function getToken() {
  if (memoryToken) return memoryToken
  const stored = readStored()
  if (stored && TOKEN_FORMAT.test(stored)) {
    memoryToken = stored
    return stored
  }
  return null
}

export function setToken(token) {
  memoryToken = token
  writeStored(token)
}

export function clearToken() {
  memoryToken = null
  writeStored(null)
}

// Takes the secret out of the address the page was opened with, keeps it, and
// removes it from the address bar and the history entry. The fragment is removed
// whatever it holds. Returns whether a usable secret was found.
export function captureTokenFromLocation(win = globalThis.window) {
  if (!win?.location) return false
  const match = /(?:^#|&)token=([^&]*)/.exec(win.location.hash || '')
  if (!match) return false
  try {
    win.history.replaceState(win.history.state, '', win.location.pathname + win.location.search)
  } catch {
    // leaving it in the address bar is not worth failing for
  }
  let token
  try {
    token = decodeURIComponent(match[1])
  } catch {
    return false
  }
  if (!TOKEN_FORMAT.test(token)) return false
  setToken(token)
  reportConnected() // a new secret makes any earlier "not connected" notice stale
  return true
}

// Whether the app has refused this browser (a 401). Any call, from any page, can
// find out, and the layout shows one explanation for all of them instead of every
// page treating the refusal as "no data".
let notConnected = false
const listeners = new Set()

function emit() {
  listeners.forEach((listener) => listener())
}

export function reportNotConnected() {
  if (!notConnected) {
    notConnected = true
    emit()
  }
}

export function reportConnected() {
  if (notConnected) {
    notConnected = false
    emit()
  }
}

export function isNotConnected() {
  return notConnected
}

export function subscribeNotConnected(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
