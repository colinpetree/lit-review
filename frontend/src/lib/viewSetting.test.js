import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_VIEW, getView } from './viewSetting'

afterEach(() => vi.unstubAllGlobals())

function stubStorage(store) {
  vi.stubGlobal('localStorage', {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      store[k] = v
    },
  })
}

describe('getView', () => {
  it('defaults to the table', () => {
    stubStorage({})
    expect(DEFAULT_VIEW).toBe('table')
    expect(getView()).toBe('table')
  })

  it.each(['table', 'card'])('reads a saved %s view', (value) => {
    stubStorage({ 'lit-review.list-view': value })
    expect(getView()).toBe(value)
  })

  it('falls back to the default for a damaged value', () => {
    stubStorage({ 'lit-review.list-view': 'grid' })
    expect(getView()).toBe('table')
  })

  it('falls back to the default when storage is blocked', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
    })
    expect(getView()).toBe('table')
  })
})
