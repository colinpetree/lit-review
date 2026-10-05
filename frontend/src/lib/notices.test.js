import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchNotices, forgetNotices } from './notices'

function respond(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

beforeEach(() => forgetNotices())
afterEach(() => vi.unstubAllGlobals())

describe('fetchNotices', () => {
  it('returns the text the app sends', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ text: 'Lit Review includes' }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await fetchNotices()).toBe('Lit Review includes')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/notices')
  })

  it('asks only once: reopening the dialog uses what it already has', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ text: 'notices' }))
    vi.stubGlobal('fetch', fetchMock)
    await fetchNotices()
    await fetchNotices()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("throws the app's message when the file is missing", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ error: 'The notices file is made when the app is built' }, 404)))
    await expect(fetchNotices()).rejects.toThrow('The notices file is made when the app is built')
  })

  it('does not keep a failure: trying again asks again', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ error: 'Nope' }, 500))
      .mockResolvedValueOnce(respond({ text: 'second time' }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(fetchNotices()).rejects.toThrow('Nope')
    expect(await fetchNotices()).toBe('second time')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('fails on a network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(fetchNotices()).rejects.toThrow('Failed to fetch')
  })

  it('refuses an answer that has no text, or only blank text, and does not keep it', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond({ other: 1 }))
      .mockResolvedValueOnce(respond({ text: '  \n' }))
      .mockResolvedValueOnce(respond({ text: 'real' }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(fetchNotices()).rejects.toThrow('Unexpected response')
    await expect(fetchNotices()).rejects.toThrow('Unexpected response')
    expect(await fetchNotices()).toBe('real')
  })
})
