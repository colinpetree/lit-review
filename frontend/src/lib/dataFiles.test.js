import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadBackup, restoreBackup } from './dataFiles'

afterEach(() => vi.unstubAllGlobals())

function reply(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

describe('restoreBackup', () => {
  it('sends the file itself as the body, not a form, and returns the answer', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply({ ok: true, message: 'Backup restored.', safety_copy: 'x' }))
    vi.stubGlobal('fetch', fetchMock)
    const file = new Blob(['SQLite format 3'])
    expect(await restoreBackup(file)).toEqual({ ok: true, message: 'Backup restored.', safety_copy: 'x' })
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/data/restore')
    expect(options.method).toBe('POST')
    expect(options.body).toBe(file)
    expect(options.headers['Content-Type']).toBe('application/octet-stream')
  })

  it("throws the server's message and status when it refuses the backup", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ error: 'That file is not a Lit Review backup.' }, 400)))
    const error = await restoreBackup(new Blob(['x'])).catch((e) => e)
    expect(error.message).toBe('That file is not a Lit Review backup.')
    expect(error.status).toBe(400)
  })

  it('falls back to the status when the reply is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => Promise.reject(new Error('x')) }))
    await expect(restoreBackup(new Blob(['x']))).rejects.toThrow('The restore failed (502).')
  })
})

describe('downloadBackup', () => {
  it('throws the error when the backup cannot be made', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ error: 'The backup could not be made.' }, 500)))
    await expect(downloadBackup()).rejects.toThrow('The backup could not be made.')
  })
})
