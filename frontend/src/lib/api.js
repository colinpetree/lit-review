import { getToken, reportConnected, reportNotConnected } from './session'

// Every call to the app's API goes through here, so each carries the secret as an
// Authorization header (a header the page's own script sets, never a cookie: see
// lib/session.js), and a refusal (401) is noticed in one place.
export async function apiFetch(url, options = {}) {
  const token = getToken()
  // A plain object, a Headers instance or a list of pairs all work (spreading a
  // Headers instance would silently drop every header in it).
  const given = options.headers ?? {}
  const headers = given instanceof Headers || Array.isArray(given) ? Object.fromEntries(new Headers(given)) : { ...given }
  const hasAuthorization = Object.keys(headers).some((name) => name.toLowerCase() === 'authorization')
  if (token && !hasAuthorization) headers.Authorization = `Bearer ${token}`
  const res = await fetch(url, { ...options, headers })
  if (res.status === 401) reportNotConnected()
  else if (res.ok) reportConnected()
  return res
}

export async function fetchJson(url, options) {
  const res = await apiFetch(url, options)
  let data
  try {
    data = await res.json()
  } catch {
    // A non-JSON body (an HTML error page from a proxy in front of the
    // backend, for example) means we can't trust anything but the status.
    throw new Error(`Unexpected response from the server (${res.status}).`)
  }
  if (!res.ok) {
    // The status lets callers treat some failures specially (409: busy).
    const error = new Error(data.error || `Request failed (${res.status})`)
    error.status = res.status
    throw error
  }
  return data
}

export function postJson(url, body, options) {
  return fetchJson(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    ...options,
  })
}

export function deleteJson(url, options) {
  return fetchJson(url, { method: 'DELETE', ...options })
}

export function patchJson(url, body, options) {
  return fetchJson(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    ...options,
  })
}
