import { describe, expect, it } from 'vitest'
import { PAGE_SIZE, shownCount, showMore } from './paging'

describe('paging', () => {
  it('starts at one page and grows a page at a time', () => {
    let state = { key: 'a', count: PAGE_SIZE }
    expect(shownCount(state, 'a')).toBe(20)
    state = showMore(state, 'a')
    expect(shownCount(state, 'a')).toBe(40)
    state = showMore(state, 'a')
    expect(shownCount(state, 'a')).toBe(60)
  })

  it('starts again when the key changes', () => {
    const state = { key: 'a', count: 80 }
    expect(shownCount(state, 'b')).toBe(20)
    expect(shownCount(showMore(state, 'b'), 'b')).toBe(40)
  })
})
