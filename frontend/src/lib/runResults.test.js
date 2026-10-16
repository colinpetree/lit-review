import { describe, expect, it } from 'vitest'
import { mergeRunResults } from './runResults'

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
