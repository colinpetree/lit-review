import { afterEach, describe, expect, it, vi } from 'vitest'
import { deleteJson, fetchJson, patchJson, postJson } from './api'

function respond(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

afterEach(() => vi.unstubAllGlobals())

describe('fetchJson', () => {
  it('returns the parsed body on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ a: 1 })))
    expect(await fetchJson('/x')).toEqual({ a: 1 })
  })

  it("throws the server's error message", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ error: 'Nope' }, 400)))
    await expect(fetchJson('/x')).rejects.toThrow('Nope')
  })

  it('puts the HTTP status on the error so callers can treat some failures specially', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ error: 'busy' }, 409)))
    const error = await fetchJson('/x').catch((e) => e)
    expect(error).toBeInstanceOf(Error)
    expect(error.status).toBe(409)
    expect(error.message).toBe('busy')
  })

  it('falls back to the status when the error has no message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({}, 500)))
    await expect(fetchJson('/x')).rejects.toThrow('Request failed (500)')
  })

  it('does not trust a body that is not JSON', async () => {
    const res = { ok: false, status: 502, json: async () => Promise.reject(new SyntaxError('bad')) }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(res))
    await expect(fetchJson('/x')).rejects.toThrow('Unexpected response from the server (502).')
  })
})

describe('request helpers', () => {
  it('send JSON bodies with the right method and header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await postJson('/p', { a: 1 })
    await patchJson('/q', { b: 2 })
    await deleteJson('/r')

    const [post, patch, del] = fetchMock.mock.calls
    expect(post[1]).toMatchObject({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"a":1}' })
    expect(patch[1]).toMatchObject({ method: 'PATCH', body: '{"b":2}' })
    expect(del[1]).toMatchObject({ method: 'DELETE' })
  })

  it('pass extra options such as an abort signal through', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({}))
    vi.stubGlobal('fetch', fetchMock)
    const { signal } = new AbortController()
    await postJson('/p', {}, { signal })
    expect(fetchMock.mock.calls[0][1].signal).toBe(signal)
  })
})
