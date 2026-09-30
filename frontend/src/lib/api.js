export async function fetchJson(url, options) {
  const res = await fetch(url, options)
  let data
  try {
    data = await res.json()
  } catch {
    // A non-JSON body (an HTML error page from a proxy in front of the
    // backend, for example) means we can't trust anything but the status.
    throw new Error(`Unexpected response from the server (${res.status}).`)
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
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

export function patchJson(url, body, options) {
  return fetchJson(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    ...options,
  })
}
