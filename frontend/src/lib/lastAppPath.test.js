import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_APP_PATH, forgetAppPath, lastAppPath, rememberAppPath } from './lastAppPath'

function stubStorage(store) {
  vi.stubGlobal('sessionStorage', {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      store[k] = v
    },
    removeItem: (k) => {
      delete store[k]
    },
  })
}

const throwing = () => {
  throw new Error('blocked')
}

beforeEach(() => stubStorage({}))
afterEach(() => {
  forgetAppPath()
  vi.unstubAllGlobals()
})

describe('lastAppPath', () => {
  it('falls back to Discover Papers when nothing was visited', () => {
    expect(lastAppPath()).toBe(DEFAULT_APP_PATH)
  })

  it('remembers the path and query of the last app page', () => {
    rememberAppPath({ pathname: '/datasets/7', search: '?filter=new' })
    expect(lastAppPath()).toBe('/datasets/7?filter=new')
    rememberAppPath({ pathname: '/results' })
    expect(lastAppPath()).toBe('/results')
  })

  it('ignores the Deleted Items page, so Back skips over it', () => {
    rememberAppPath({ pathname: '/evaluate', search: '' })
    rememberAppPath({ pathname: '/trash' })
    expect(lastAppPath()).toBe('/evaluate')
  })

  it('does not treat a path that only starts with the word trash as that page', () => {
    rememberAppPath({ pathname: '/trashfoo' })
    expect(lastAppPath()).toBe('/trashfoo')
  })

  it('works from memory when storage throws', () => {
    vi.stubGlobal('sessionStorage', { getItem: throwing, setItem: throwing, removeItem: throwing })
    rememberAppPath({ pathname: '/prompts/3' })
    expect(lastAppPath()).toBe('/prompts/3')
  })

  it('survives a reload, where memory is empty but storage is not', () => {
    const store = { 'lit-review-last-app-path': '/results/4' }
    stubStorage(store)
    expect(lastAppPath()).toBe('/results/4')
  })

  it.each(['https://evil.example/', '//evil.example', 'datasets', '/trash', 42])(
    'ignores a stored value that is not an in-app path (%s)',
    (value) => {
      stubStorage({ 'lit-review-last-app-path': value })
      expect(lastAppPath()).toBe(DEFAULT_APP_PATH)
    },
  )
})
