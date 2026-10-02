import { afterEach, describe, expect, it, vi } from 'vitest'
import { driveFindAbstracts, getLookup, startLookup, subscribeLookup } from './findAbstracts'

function respond(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

const chunk = (patch) => ({
  attempted: [],
  filled: [],
  checked: [],
  remaining: 0,
  no_doi: 0,
  source_errors: {},
  ...patch,
})

const bodyOf = (fetchMock, call) => JSON.parse(fetchMock.mock.calls[call][1].body)

afterEach(() => vi.unstubAllGlobals())

describe('driveFindAbstracts', () => {
  it('keeps asking until nothing remains, sending back what was already tried', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond(chunk({ attempted: [1, 2], filled: [{ id: 1 }], remaining: 2, no_doi: 3 })))
      .mockResolvedValueOnce(respond(chunk({ attempted: [3, 4], checked: [3, 4], remaining: 0, no_doi: 3 })))
    vi.stubGlobal('fetch', fetchMock)
    const seen = []

    const result = await driveFindAbstracts(9, undefined, (p) => seen.push(p))

    expect(fetchMock.mock.calls[0][0]).toBe('/api/datasets/9/find-abstracts')
    expect(bodyOf(fetchMock, 0)).toEqual({ skip_ids: [], skip_sources: [] })
    expect(bodyOf(fetchMock, 1)).toEqual({ skip_ids: [1, 2], skip_sources: [] })
    expect(seen).toHaveLength(2)
    expect(result).toMatchObject({ filledCount: 1, attempted: 4, total: 4, noDoi: 3 })
  })

  it('stops using a source after it reports an error', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(respond(chunk({ attempted: [1], remaining: 1, source_errors: { elsevier: 'Key rejected.' } })))
      .mockResolvedValueOnce(respond(chunk({ attempted: [2], remaining: 0 })))
    vi.stubGlobal('fetch', fetchMock)

    const result = await driveFindAbstracts(1, undefined, () => {})

    expect(bodyOf(fetchMock, 1).skip_sources).toEqual(['elsevier'])
    expect(result.sourceErrors).toEqual({ elsevier: 'Key rejected.' })
  })

  it('stops on an empty chunk even if the server still reports some remaining', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(chunk({ attempted: [], remaining: 5 })))
    vi.stubGlobal('fetch', fetchMock)

    await driveFindAbstracts(1, undefined, () => {})

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('surfaces a server error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ error: 'dataset not found' }, 404)))
    await expect(driveFindAbstracts(1, undefined, () => {})).rejects.toThrow('dataset not found')
  })
})

describe('startLookup', () => {
  it('runs in the background, notifies subscribers and forgets the lookup when done', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(chunk({ attempted: [1], filled: [{ id: 1 }] })))
    vi.stubGlobal('fetch', fetchMock)
    const states = []
    const finished = new Promise((resolve) => {
      subscribeLookup(42, (state) => {
        states.push(state)
        if (!state.running) resolve()
      })
    })

    startLookup(42)
    startLookup(42) // already running: ignored
    expect(getLookup(42).running).toBe(true)
    await finished

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(states.at(-1).running).toBe(false)
    expect(states.some((s) => s.filledPapers?.length === 1)).toBe(true)
    // The lookup is forgotten a moment after the final notification.
    await vi.waitFor(() => expect(getLookup(42)).toBeNull())
  })

  it('reports a failure instead of throwing', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond({ error: 'boom' }, 500)))
    const finished = new Promise((resolve) => {
      subscribeLookup(43, (state) => {
        if (!state.running) resolve(state)
      })
    })

    startLookup(43)

    expect((await finished).error).toBe('boom')
  })
})
