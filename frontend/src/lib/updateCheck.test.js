import { afterEach, describe, expect, it, vi } from 'vitest'
import { getDismissedVersion, getUpdateCheckEnabled, shouldShowUpdate } from './updateCheck'

afterEach(() => vi.unstubAllGlobals())

function stubStorage(store) {
  vi.stubGlobal('localStorage', {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      store[k] = v
    },
  })
}

const release = {
  current: '0.1.0',
  latest: '0.2.0',
  newer: true,
  url: 'https://github.com/colinpetree/lit-review/releases/tag/v0.2.0',
}

describe('shouldShowUpdate', () => {
  it('shows a newer release', () => {
    expect(shouldShowUpdate(release, null)).toBe(true)
  })

  it('does not show when there is nothing newer or nothing was heard', () => {
    expect(shouldShowUpdate({ ...release, newer: false }, null)).toBe(false)
    expect(shouldShowUpdate(null, null)).toBe(false)
    expect(shouldShowUpdate(undefined, null)).toBe(false)
  })

  it('does not show a release without a link it can open', () => {
    expect(shouldShowUpdate({ ...release, url: null }, null)).toBe(false)
    expect(shouldShowUpdate({ ...release, url: 'javascript:alert(1)' }, null)).toBe(false)
  })

  it('stays hidden for a dismissed version, but a later one shows again', () => {
    expect(shouldShowUpdate(release, '0.2.0')).toBe(false)
    expect(shouldShowUpdate({ ...release, latest: '0.3.0' }, '0.2.0')).toBe(true)
  })

  it('needs newer to be exactly true', () => {
    expect(shouldShowUpdate({ ...release, newer: 'yes' }, null)).toBe(false)
  })
})

describe('the saved choices', () => {
  it('checks by default, and off only when switched off', () => {
    stubStorage({})
    expect(getUpdateCheckEnabled()).toBe(true)
    stubStorage({ 'lit-review.update-check': 'false' })
    expect(getUpdateCheckEnabled()).toBe(false)
    stubStorage({ 'lit-review.update-check': 'true' })
    expect(getUpdateCheckEnabled()).toBe(true)
  })

  it('remembers the dismissed version', () => {
    stubStorage({ 'lit-review.update-dismissed': '0.2.0' })
    expect(getDismissedVersion()).toBe('0.2.0')
  })

  it('copes with storage that throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
    })
    expect(getUpdateCheckEnabled()).toBe(true)
    expect(getDismissedVersion()).toBe(null)
  })
})
