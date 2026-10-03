import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, deleteJson, fetchJson, patchJson, postJson } from './api'
import { clearToken, isNotConnected, reportConnected, reportNotConnected, setToken } from './session'

const TOKEN = 'abcDEF123_-xyzABC456_-abcDEF123_-xyzABC456'

function respond(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function stubFetch(reply = respond({})) {
  const fetchMock = vi.fn().mockResolvedValue(reply)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const sentHeaders = (fetchMock, call = 0) => fetchMock.mock.calls[call][1].headers

beforeEach(() => {
  vi.stubGlobal('localStorage', undefined)
  clearToken()
  reportConnected()
})

afterEach(() => {
  vi.unstubAllGlobals()
  clearToken()
  reportConnected()
})

describe('the secret goes in a header, on every kind of call', () => {
  it('is sent as a bearer token', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await fetchJson('/api/datasets')
    expect(sentHeaders(fetchMock)).toMatchObject({ Authorization: `Bearer ${TOKEN}` })
  })

  it('is sent by every helper', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await fetchJson('/api/a')
    await postJson('/api/b', { x: 1 })
    await patchJson('/api/c', { x: 1 })
    await deleteJson('/api/d')
    await apiFetch('/api/e')
    for (let call = 0; call < 5; call += 1) {
      expect(sentHeaders(fetchMock, call).Authorization).toBe(`Bearer ${TOKEN}`)
    }
  })

  it('is read at the moment of the call, so a secret kept later is used straight away', async () => {
    const fetchMock = stubFetch()
    await fetchJson('/api/a')
    setToken(TOKEN)
    await fetchJson('/api/b')
    expect(sentHeaders(fetchMock, 0).Authorization).toBeUndefined()
    expect(sentHeaders(fetchMock, 1).Authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('is not sent when there is none', async () => {
    const fetchMock = stubFetch()
    await fetchJson('/api/a')
    expect(Object.keys(sentHeaders(fetchMock))).not.toContain('Authorization')
  })

  it('leaves the other headers, the method and the body as they were', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await postJson('/api/b', { x: 1 })
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: '{"x":1}',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` },
    })
  })

  it('keeps an Authorization header the caller set, in any letter case', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await apiFetch('/api/a', { headers: { authorization: 'Bearer something-else' } })
    expect(sentHeaders(fetchMock)).toEqual({ authorization: 'Bearer something-else' })
  })

  it('keeps the caller\'s headers however they are given: a plain object, a Headers instance or pairs', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await apiFetch('/api/a', { headers: { 'Content-Type': 'application/json' } })
    await apiFetch('/api/a', { headers: new Headers({ 'Content-Type': 'application/json' }) })
    await apiFetch('/api/a', { headers: [['Content-Type', 'application/json']] })
    for (let call = 0; call < 3; call += 1) {
      const sent = Object.fromEntries(Object.entries(sentHeaders(fetchMock, call)).map(([k, v]) => [k.toLowerCase(), v]))
      expect(sent['content-type']).toBe('application/json')
      expect(sent.authorization).toBe(`Bearer ${TOKEN}`)
    }
  })

  it('does not add a second Authorization header when a Headers instance already has one', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await apiFetch('/api/a', { headers: new Headers({ Authorization: 'Bearer something-else' }) })
    const names = Object.keys(sentHeaders(fetchMock)).map((name) => name.toLowerCase())
    expect(names.filter((name) => name === 'authorization')).toHaveLength(1)
    expect(Object.values(sentHeaders(fetchMock))).toContain('Bearer something-else')
  })

  it('does not change the options object the caller passed in', async () => {
    setToken(TOKEN)
    stubFetch()
    const options = { method: 'GET', headers: { 'X-Test': '1' } }
    await apiFetch('/api/a', options)
    expect(options).toEqual({ method: 'GET', headers: { 'X-Test': '1' } })
  })

  it('passes an abort signal through', async () => {
    const fetchMock = stubFetch()
    const { signal } = new AbortController()
    await apiFetch('/api/a', { signal })
    expect(fetchMock.mock.calls[0][1].signal).toBe(signal)
  })

  it('never puts the secret in the address', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await fetchJson('/api/datasets?x=1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/datasets?x=1')
  })

  it('does not rely on cookies: nothing asks the browser to send them or to keep them', async () => {
    setToken(TOKEN)
    const fetchMock = stubFetch()
    await fetchJson('/api/a')
    const options = fetchMock.mock.calls[0][1]
    expect(options.credentials).toBeUndefined() // the default: same-origin cookies, but none are used or needed
    expect(Object.keys(options.headers).map((h) => h.toLowerCase())).not.toContain('cookie')
  })

  it('returns the response itself', async () => {
    const reply = respond({ ok: true })
    stubFetch(reply)
    expect(await apiFetch('/api/a')).toBe(reply)
  })
})

describe('a refusal is noticed in one place', () => {
  it('a 401 turns the notice on and still fails with the server\'s message and status', async () => {
    stubFetch(respond({ error: 'This browser is not connected to Lit Review.' }, 401))
    const error = await fetchJson('/api/datasets').catch((e) => e)
    expect(error.message).toBe('This browser is not connected to Lit Review.')
    expect(error.status).toBe(401)
    expect(isNotConnected()).toBe(true)
  })

  it('works for the raw helper too, without reading the body', async () => {
    stubFetch(respond({}, 401))
    await apiFetch('/api/datasets')
    expect(isNotConnected()).toBe(true)
  })

  it('a later success turns it off again', async () => {
    reportNotConnected()
    stubFetch(respond({ datasets: [] }))
    await fetchJson('/api/datasets')
    expect(isNotConnected()).toBe(false)
  })

  it('other failures neither turn it on nor off', async () => {
    stubFetch(respond({ error: 'boom' }, 500))
    await fetchJson('/api/a').catch(() => {})
    expect(isNotConnected()).toBe(false)
    reportNotConnected()
    stubFetch(respond({ error: 'busy' }, 409))
    await fetchJson('/api/a').catch(() => {})
    expect(isNotConnected()).toBe(true)
  })

  it('a network failure leaves it alone and is thrown', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(fetchJson('/api/a')).rejects.toThrow('Failed to fetch')
    expect(isNotConnected()).toBe(false)
  })

  it('an HTML 401 from something in front of the app still counts', async () => {
    const reply = { ok: false, status: 401, json: async () => Promise.reject(new SyntaxError('not json')) }
    stubFetch(reply)
    await expect(fetchJson('/api/a')).rejects.toThrow('Unexpected response from the server (401).')
    expect(isNotConnected()).toBe(true)
  })
})
