import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  NOT_CONNECTED_MESSAGE,
  captureTokenFromLocation,
  clearToken,
  getToken,
  isNotConnected,
  reportConnected,
  reportNotConnected,
  setToken,
  subscribeNotConnected,
} from './session'

const TOKEN = 'abcDEF123_-xyzABC456_-abcDEF123_-xyzABC456'

// What a browser keeps for one address: a Map behind the localStorage interface.
function fakeStorage(overrides = {}) {
  const map = new Map()
  return {
    map,
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => void map.set(key, String(value)),
    removeItem: (key) => void map.delete(key),
    ...overrides,
  }
}

function fakeWindow({ hash = '', pathname = '/', search = '' } = {}) {
  return {
    location: { hash, pathname, search },
    history: { state: { from: 'test' }, replaceState: vi.fn() },
  }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', fakeStorage())
  clearToken()
  reportConnected()
})

afterEach(() => {
  vi.unstubAllGlobals()
  clearToken()
  reportConnected()
})

describe('captureTokenFromLocation', () => {
  it('takes the secret from the address, keeps it, and removes it from the address bar', () => {
    const win = fakeWindow({ hash: `#token=${TOKEN}`, pathname: '/discover', search: '?q=coral' })

    expect(captureTokenFromLocation(win)).toBe(true)

    expect(getToken()).toBe(TOKEN)
    expect(win.history.replaceState).toHaveBeenCalledWith({ from: 'test' }, '', '/discover?q=coral')
  })

  it('keeps it in storage so the next visit needs no link', () => {
    captureTokenFromLocation(fakeWindow({ hash: `#token=${TOKEN}` }))
    expect(localStorage.getItem('lit-review-access')).toBe(TOKEN)
  })

  it('finds it among other fragment parts', () => {
    expect(captureTokenFromLocation(fakeWindow({ hash: `#a=1&token=${TOKEN}&b=2` }))).toBe(true)
    expect(getToken()).toBe(TOKEN)
  })

  it('decodes a percent-encoded secret', () => {
    expect(captureTokenFromLocation(fakeWindow({ hash: `#token=${encodeURIComponent(TOKEN)}` }))).toBe(true)
    expect(getToken()).toBe(TOKEN)
  })

  it.each([
    ['empty', '#token='],
    ['too short', '#token=abc'],
    ['spaces', '#token=' + 'a b '.repeat(10)],
    ['characters a secret never has', '#token=' + 'a/b+c='.repeat(8)],
    ['a script', '#token=<script>alert(1)</script>'],
    ['too long', '#token=' + 'A'.repeat(201)],
    ['a bad percent escape', '#token=%E0%A4%A'],
  ])('refuses %s, but still removes it from the address bar', (_label, hash) => {
    const win = fakeWindow({ hash })
    expect(captureTokenFromLocation(win)).toBe(false)
    expect(getToken()).toBeNull()
    expect(win.history.replaceState).toHaveBeenCalledTimes(1)
  })

  it('does nothing when the address has no secret', () => {
    for (const hash of ['', '#', '#section', '#other=1', '#tokenx=abc', '#xtoken=' + TOKEN]) {
      const win = fakeWindow({ hash })
      expect(captureTokenFromLocation(win)).toBe(false)
      expect(win.history.replaceState).not.toHaveBeenCalled()
    }
    expect(getToken()).toBeNull()
  })

  it('does not fail if the address bar cannot be changed', () => {
    const win = fakeWindow({ hash: `#token=${TOKEN}` })
    win.history.replaceState = () => {
      throw new Error('blocked')
    }
    expect(captureTokenFromLocation(win)).toBe(true)
    expect(getToken()).toBe(TOKEN)
  })

  it('does nothing outside a browser', () => {
    expect(captureTokenFromLocation(undefined)).toBe(false)
    expect(captureTokenFromLocation({})).toBe(false)
  })

  it('replaces an earlier secret, as after the app was reset', () => {
    setToken('old'.padEnd(30, 'x'))
    captureTokenFromLocation(fakeWindow({ hash: `#token=${TOKEN}` }))
    expect(getToken()).toBe(TOKEN)
  })

  it('does not touch the stored secret when the link holds a bad one', () => {
    setToken(TOKEN)
    captureTokenFromLocation(fakeWindow({ hash: '#token=short' }))
    expect(getToken()).toBe(TOKEN)
  })

  it('clears an earlier "not connected" notice, since the secret is new', () => {
    reportNotConnected()
    captureTokenFromLocation(fakeWindow({ hash: `#token=${TOKEN}` }))
    expect(isNotConnected()).toBe(false)
  })
})

describe('getToken and its storage', () => {
  it('is null before there is a secret', () => {
    expect(getToken()).toBeNull()
  })

  it('reads a stored secret on a fresh page load', () => {
    localStorage.setItem('lit-review-access', TOKEN)
    expect(getToken()).toBe(TOKEN)
  })

  it('ignores stored text that is not a secret', () => {
    localStorage.setItem('lit-review-access', 'not a secret!')
    expect(getToken()).toBeNull()
  })

  it('still works when storage throws, for as long as the page is open', () => {
    const broken = () => {
      throw new Error('storage is blocked')
    }
    vi.stubGlobal('localStorage', { getItem: broken, setItem: broken, removeItem: broken })
    clearToken()
    setToken(TOKEN)
    expect(getToken()).toBe(TOKEN)
    clearToken()
    expect(getToken()).toBeNull()
  })

  it('still works when there is no storage at all', () => {
    vi.stubGlobal('localStorage', undefined)
    clearToken()
    setToken(TOKEN)
    expect(getToken()).toBe(TOKEN)
  })

  it('forgets the secret in memory and storage when cleared', () => {
    setToken(TOKEN)
    clearToken()
    expect(getToken()).toBeNull()
    expect(localStorage.getItem('lit-review-access')).toBeNull()
  })
})

describe('the "not connected" notice', () => {
  it('starts off, turns on when the app refuses, and off when it accepts', () => {
    expect(isNotConnected()).toBe(false)
    reportNotConnected()
    expect(isNotConnected()).toBe(true)
    reportConnected()
    expect(isNotConnected()).toBe(false)
  })

  it('tells listeners once per change, not once per call', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeNotConnected(listener)
    reportNotConnected()
    reportNotConnected()
    reportNotConnected()
    expect(listener).toHaveBeenCalledTimes(1)
    reportConnected()
    reportConnected()
    expect(listener).toHaveBeenCalledTimes(2)
    unsubscribe()
  })

  it('stops telling a listener that unsubscribed', () => {
    const listener = vi.fn()
    subscribeNotConnected(listener)()
    reportNotConnected()
    expect(listener).not.toHaveBeenCalled()
  })

  it('tells every listener', () => {
    const a = vi.fn()
    const b = vi.fn()
    const offA = subscribeNotConnected(a)
    const offB = subscribeNotConnected(b)
    reportNotConnected()
    expect(a).toHaveBeenCalledTimes(1)
    expect(b).toHaveBeenCalledTimes(1)
    offA()
    offB()
  })
})

describe('the message', () => {
  it('is the same words the server uses in its refusal, so a banner and an error never disagree', () => {
    const source = readFileSync(new URL('../../../backend/app.py', import.meta.url), 'utf8')
    const block = /NOT_CONNECTED_MESSAGE = \(([\s\S]*?)\)\r?\n/.exec(source)[1]
    const serverMessage = [...block.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]).join('')
    expect(NOT_CONNECTED_MESSAGE).toBe(serverMessage)
  })
})
