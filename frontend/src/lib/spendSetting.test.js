import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_THRESHOLD_TEXT,
  LIMIT_MARGIN,
  formatUsd,
  getSpendThreshold,
  getSpendThresholdText,
  limitFor,
  needsConfirmation,
  parseThreshold,
} from './spendSetting'

afterEach(() => vi.unstubAllGlobals())

function stubStorage(store) {
  vi.stubGlobal('localStorage', {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      store[k] = v
    },
  })
}

describe('parseThreshold', () => {
  it.each([
    ['1', 1],
    ['1.50', 1.5],
    ['0', 0],
    ['0.25', 0.25],
    ['.5', 0.5],
    ['$2', 2],
    [' 3 ', 3],
  ])('reads %s as %s', (text, value) => {
    expect(parseThreshold(text)).toBe(value)
  })

  it.each(['', '   ', null, undefined, '$'])('reads %s as "never ask"', (text) => {
    expect(parseThreshold(text)).toBeNull()
  })

  it.each(['abc', '-1', '1.234', '1,5', '1e3', 'NaN', 'Infinity', '1 2'])('rejects %s', (text) => {
    expect(parseThreshold(text)).toBeUndefined()
  })
})

describe('needsConfirmation', () => {
  it('asks only above the threshold', () => {
    expect(needsConfirmation(1.01, 1)).toBe(true)
    expect(needsConfirmation(1, 1)).toBe(false)
    expect(needsConfirmation(0.2, 1)).toBe(false)
  })

  it('always asks when the threshold is 0, even for a free run', () => {
    expect(needsConfirmation(0, 0)).toBe(true)
    expect(needsConfirmation(0.001, 0)).toBe(true)
  })

  it('never asks when there is no threshold', () => {
    expect(needsConfirmation(500, null)).toBe(false)
    expect(needsConfirmation(500, undefined)).toBe(false)
  })
})

describe('limitFor', () => {
  it('gives a confirmed run room above its estimate, rounded up to the cent', () => {
    expect(limitFor({ usd: 2, threshold: 1, confirmed: true })).toBe(2.5)
    expect(limitFor({ usd: 1.234, threshold: 1, confirmed: true })).toBe(Math.ceil(1.234 * LIMIT_MARGIN * 100) / 100)
  })

  it('never gives a confirmed run a zero limit', () => {
    expect(limitFor({ usd: 0, threshold: 0, confirmed: true })).toBe(0.01)
  })

  it('limits a run that needed no confirmation to the threshold', () => {
    expect(limitFor({ usd: 0.3, threshold: 1, confirmed: false })).toBe(1)
  })

  it('has no limit when the user never wants to be asked', () => {
    expect(limitFor({ usd: 0.3, threshold: null, confirmed: false })).toBeNull()
    expect(limitFor({ usd: 50, threshold: null, confirmed: false })).toBeNull()
  })
})

describe('what is stored', () => {
  it('starts at the default', () => {
    stubStorage({})
    expect(getSpendThresholdText()).toBe(DEFAULT_THRESHOLD_TEXT)
    expect(getSpendThreshold()).toBe(1)
  })

  it('keeps a blank choice as "never ask" instead of falling back to the default', () => {
    stubStorage({ 'lit-review.spend-confirm-usd': '' })
    expect(getSpendThreshold()).toBeNull()
  })

  it('reads a saved amount, including 0', () => {
    stubStorage({ 'lit-review.spend-confirm-usd': '0' })
    expect(getSpendThreshold()).toBe(0)
  })

  it('treats a damaged value as the default, not as "never ask"', () => {
    stubStorage({ 'lit-review.spend-confirm-usd': 'lots' })
    expect(getSpendThreshold()).toBe(1)
  })

  it('uses the default when storage throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
    })
    expect(getSpendThreshold()).toBe(1)
  })
})

describe('formatUsd', () => {
  it.each([
    [0.123, '$0.12'],
    [12.4, '$12.40'],
    [0, '$0.00'],
    [0.004, 'under $0.01'],
    [NaN, ''],
  ])('shows %s as %s', (usd, text) => {
    expect(formatUsd(usd)).toBe(text)
  })
})
