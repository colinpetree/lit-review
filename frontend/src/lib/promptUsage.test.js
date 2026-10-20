import { describe, expect, it } from 'vitest'
import { promptsUsedBy } from './promptUsage'

const run = (id, promptId, at, extra = {}) => ({
  id,
  prompt_id: promptId,
  prompt_name: `Prompt ${promptId}`,
  created_at: at,
  completed_at: null,
  ...extra,
})

describe('promptsUsedBy', () => {
  it('counts each prompt once, with its latest use', () => {
    const runs = [run(1, 7, '2026-01-01T00:00:00'), run(2, 7, '2026-03-01T00:00:00')]
    const [entry, ...rest] = promptsUsedBy(runs, [{ id: 7, name: 'Coral', example_count: 4 }])
    expect(rest).toEqual([])
    expect(entry).toEqual({
      id: 7,
      name: 'Coral',
      deleted: false,
      examples: 4,
      evaluations: 2,
      lastUsed: '2026-03-01T00:00:00',
    })
  })

  it('uses the completion time when there is one', () => {
    const runs = [run(1, 7, '2026-01-01T00:00:00', { completed_at: '2026-05-01T00:00:00' })]
    expect(promptsUsedBy(runs, [])[0].lastUsed).toBe('2026-05-01T00:00:00')
  })

  it('marks a prompt that is not in the live list as deleted', () => {
    const [entry] = promptsUsedBy([run(1, 9, '2026-01-01T00:00:00')], [])
    expect(entry.deleted).toBe(true)
    expect(entry.examples).toBe(null)
    expect(entry.name).toBe('Prompt 9')
  })

  it('skips a run with no prompt', () => {
    expect(promptsUsedBy([run(1, null, '2026-01-01T00:00:00')], [])).toEqual([])
  })

  it('puts the most recently used prompt first', () => {
    const runs = [run(1, 1, '2026-01-01T00:00:00'), run(2, 2, '2026-06-01T00:00:00'), run(3, 3, '2026-03-01T00:00:00')]
    expect(promptsUsedBy(runs, []).map((p) => p.id)).toEqual([2, 3, 1])
  })
})
