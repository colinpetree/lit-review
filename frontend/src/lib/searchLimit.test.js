import { describe, expect, it } from 'vitest'
import { DEFAULT_SEARCH_LIMIT, SEARCH_LIMIT_OPTIONS, normalizeSearchLimit } from './searchLimit'

describe('search limit', () => {
  it('offers the choices the server accepts, with the default among them', () => {
    expect(SEARCH_LIMIT_OPTIONS.map((o) => o.value)).toEqual([50, 100, 200, 500])
    expect(SEARCH_LIMIT_OPTIONS.map((o) => o.value)).toContain(DEFAULT_SEARCH_LIMIT)
    expect(DEFAULT_SEARCH_LIMIT).toBe(100)
  })

  it('keeps a valid remembered value', () => {
    expect(normalizeSearchLimit(200)).toBe(200)
  })

  it('falls back to the default for anything else', () => {
    for (const value of [undefined, null, 0, 75, 2500, '100', true, [100]]) {
      expect(normalizeSearchLimit(value)).toBe(DEFAULT_SEARCH_LIMIT)
    }
  })
})
