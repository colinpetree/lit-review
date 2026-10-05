// Where the Deleted Items page's way back goes: the last page the user was on before it.

const STORAGE_KEY = 'lit-review-last-app-path'
export const DEFAULT_APP_PATH = '/discover'

let memoryPath = null

const isTrashPath = (pathname) => pathname === '/trash'

// Storage can be missing or throw (a private window, blocked site data), so the path is
// also held in memory for as long as the page stays open.
export function rememberAppPath({ pathname, search = '' }) {
  if (isTrashPath(pathname)) return
  const path = pathname + search
  memoryPath = path
  try {
    globalThis.sessionStorage?.setItem(STORAGE_KEY, path)
  } catch {
    // memory still has it
  }
}

export function lastAppPath() {
  let stored = null
  try {
    stored = globalThis.sessionStorage?.getItem(STORAGE_KEY) ?? null
  } catch {
    // fall through to memory
  }
  const path = memoryPath ?? stored
  // Only ever an in-app path: anything else (stale or tampered storage) is ignored.
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || isTrashPath(path)) {
    return DEFAULT_APP_PATH
  }
  return path
}

// For tests.
export function forgetAppPath() {
  memoryPath = null
  try {
    globalThis.sessionStorage?.removeItem(STORAGE_KEY)
  } catch {
    // nothing to clear
  }
}
