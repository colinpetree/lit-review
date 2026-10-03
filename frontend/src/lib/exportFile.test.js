import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadExport, exportMenuItem, filenameFromDisposition } from './exportFile'

afterEach(() => vi.unstubAllGlobals())

describe('filenameFromDisposition', () => {
  it("reads the server's file name", () => {
    expect(filenameFromDisposition('attachment; filename="coral-reefs-2026-10-03.csv"')).toBe('coral-reefs-2026-10-03.csv')
  })

  it.each([null, undefined, '', 'attachment'])('falls back when the header is %s', (header) => {
    expect(filenameFromDisposition(header)).toBe('papers')
  })
})

describe('downloadExport', () => {
  it("throws the server's message and status when it refuses", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ error: 'There are no papers to export.' }) })
    )
    const error = await downloadExport('/x/export', { format: 'csv' }).catch((e) => e)
    expect(error.message).toBe('There are no papers to export.')
    expect(error.status).toBe(400)
  })

  it('falls back to the status when the reply is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => Promise.reject(new Error('x')) }))
    await expect(downloadExport('/x/export', { format: 'csv' })).rejects.toThrow('The export failed (502).')
  })

  it('sends the format and chosen ids as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ error: 'no' }) })
    vi.stubGlobal('fetch', fetchMock)
    await downloadExport('/x/export', { format: 'ris', paper_ids: [3, 1] }).catch(() => {})
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/x/export')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({ format: 'ris', paper_ids: [3, 1] })
  })
})

describe('exportMenuItem', () => {
  const base = { url: '/api/datasets/1/export', all: [1, 2, 3, 4], shown: [3, 1], onError: () => {} }

  it('offers one choice per format when no filter is on', () => {
    const item = exportMenuItem({ ...base, filterActive: false })
    expect(item.submenu.map((i) => i.label)).toEqual(['CSV (4)', 'RIS (4)', 'BibTeX (4)'])
  })

  it('offers shown and all for each format when a filter is on', () => {
    const item = exportMenuItem({ ...base, filterActive: true })
    expect(item.submenu.map((i) => i.label)).toEqual([
      'CSV, shown (2)',
      'CSV, all (4)',
      'RIS, shown (2)',
      'RIS, all (4)',
      'BibTeX, shown (2)',
      'BibTeX, all (4)',
    ])
    expect(new Set(item.submenu.map((i) => i.label)).size).toBe(item.submenu.length)
  })

  it('sends the shown ids in order, or no ids for all, and reports a failure', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ error: 'Nope' }) })
    vi.stubGlobal('fetch', fetchMock)
    const onError = vi.fn()
    const item = exportMenuItem({ ...base, filterActive: true, onError })
    item.submenu[0].onClick()
    item.submenu[1].onClick()
    await vi.waitFor(() => expect(onError).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ format: 'csv', paper_ids: [3, 1] })
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ format: 'csv' })
    expect(onError).toHaveBeenCalledWith('Nope')
  })
})
