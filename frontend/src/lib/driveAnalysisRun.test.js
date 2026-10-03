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

  describe('when the server says the run is busy (409)', () => {
    const busy = () => respond({ error: 'This run is already being scored.' }, 409)
    const fast = { busyRetryMs: 1 }

    it('waits and tries again instead of failing, then carries on', async () => {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(busy())
        .mockResolvedValueOnce(busy())
        .mockResolvedValueOnce(respond(run('running', 20)))
        .mockResolvedValueOnce(respond(run('completed', 0)))
      vi.stubGlobal('fetch', fetchMock)
      const updates = []

      const final = await driveAnalysisRun(3, undefined, (r) => updates.push(r.remaining), fast)

      expect(fetchMock).toHaveBeenCalledTimes(4)
      expect(updates).toEqual([20, 0]) // the busy replies are not shown as progress
      expect(final.status).toBe('completed')
    })

    it('gives up with the 409 error after about a minute of waiting', async () => {
      const fetchMock = vi.fn().mockImplementation(async () => busy())
      vi.stubGlobal('fetch', fetchMock)

      const error = await driveAnalysisRun(3, undefined, () => {}, fast).catch((e) => e)

      expect(error.status).toBe(409)
      expect(fetchMock).toHaveBeenCalledTimes(31) // the first try plus 30 retries
    })

    it('starts counting again after a chunk goes through', async () => {
      const replies = [
        ...Array(20).fill(busy()),
        respond(run('running', 20)),
        ...Array(20).fill(busy()),
        respond(run('completed', 0)),
      ]
      const fetchMock = vi.fn().mockImplementation(async () => replies.shift())
      vi.stubGlobal('fetch', fetchMock)

      const final = await driveAnalysisRun(3, undefined, () => {}, fast)

      expect(final.status).toBe('completed') // 40 busy replies in all, never 30 in a row
    })

    it('stops waiting as soon as the request is aborted', async () => {
      const fetchMock = vi.fn().mockImplementation(async () => busy())
      vi.stubGlobal('fetch', fetchMock)
      const controller = new AbortController()

      const pending = driveAnalysisRun(3, controller.signal, () => {}, { busyRetryMs: 60_000 })
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
      controller.abort()

      await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
      expect(fetchMock).toHaveBeenCalledTimes(1) // no further request after the abort
    })

    it('does not start waiting if it was already aborted', async () => {
      vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => busy()))
      const controller = new AbortController()
      controller.abort()

      await expect(driveAnalysisRun(3, controller.signal, () => {}, fast)).rejects.toMatchObject({
        name: 'AbortError',
      })
    })

    it('does not retry any other error', async () => {
      const fetchMock = vi.fn().mockResolvedValue(respond({ error: 'Rate limit reached.' }, 400))
      vi.stubGlobal('fetch', fetchMock)

      await expect(driveAnalysisRun(3, undefined, () => {}, fast)).rejects.toThrow('Rate limit reached.')
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  })

  it('passes the abort signal to every request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(run('completed', 0)))
    vi.stubGlobal('fetch', fetchMock)
    const { signal } = new AbortController()

    await driveAnalysisRun(1, signal, () => {})

    expect(fetchMock.mock.calls[0][1].signal).toBe(signal)
  })
})
