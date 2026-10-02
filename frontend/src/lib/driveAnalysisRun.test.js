import { afterEach, describe, expect, it, vi } from 'vitest'
import { driveAnalysisRun, mergeRunResults } from './driveAnalysisRun'

function respond(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

afterEach(() => vi.unstubAllGlobals())

describe('mergeRunResults', () => {
  it('keeps unscored papers, lets scored ones replace their candidate, and sorts by score', () => {
    const run = {
      candidate_papers: [{ id: 1 }, { id: 2 }, { id: 3 }],
      results: [
        { id: 2, score: 40 },
        { id: 3, score: 90 },
      ],
    }
    const merged = mergeRunResults(run)
    expect(merged.results.map((p) => p.id)).toEqual([3, 2, 1])
    expect(merged.results[2].score).toBeUndefined()
  })
})

describe('driveAnalysisRun', () => {
  const run = (status, remaining) => ({ status, remaining, candidate_papers: [], results: [] })

  it('processes chunks until the run is completed, reporting after each one', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond(run('running', 40)))
      .mockResolvedValueOnce(respond(run('running', 20)))
      .mockResolvedValueOnce(respond(run('completed', 0)))
    vi.stubGlobal('fetch', fetchMock)
    const updates = []

    const final = await driveAnalysisRun(7, undefined, (r) => updates.push(r.remaining))

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/analysis-runs/7/process')
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(updates).toEqual([40, 20, 0])
    expect(final.status).toBe('completed')
  })

  it('stops with the error when a chunk fails', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond(run('running', 20)))
      .mockResolvedValueOnce(respond({ error: 'Rate limit reached.' }, 400))
    vi.stubGlobal('fetch', fetchMock)

    await expect(driveAnalysisRun(1, undefined, () => {})).rejects.toThrow('Rate limit reached.')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('passes the abort signal to every request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(run('completed', 0)))
    vi.stubGlobal('fetch', fetchMock)
    const { signal } = new AbortController()

    await driveAnalysisRun(1, signal, () => {})

    expect(fetchMock.mock.calls[0][1].signal).toBe(signal)
  })
})
