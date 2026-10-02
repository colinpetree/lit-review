import { describe, expect, it } from 'vitest'
import { cleanDateInput, dateBounds, dateRangeError, formatBound } from './dateRange'

describe('dateBounds', () => {
  it('turns a year into its first and last day', () => {
    expect(dateBounds('2026', '2026')).toEqual({ from: '2026-01-01', to: '2026-12-31' })
  })

  it('turns a month into its first and last day, including leap years', () => {
    expect(dateBounds('2024-02', '2024-02')).toEqual({ from: '2024-02-01', to: '2024-02-29' })
    expect(dateBounds('2025-02', '2025-02')).toEqual({ from: '2025-02-01', to: '2025-02-28' })
  })

  it('keeps a full date as typed', () => {
    expect(dateBounds('2026-03-05', '2026-04-06')).toEqual({ from: '2026-03-05', to: '2026-04-06' })
  })

  it('gives null for an empty end', () => {
    expect(dateBounds('', ' ')).toEqual({ from: null, to: null })
  })
})

describe('dateRangeError', () => {
  it('accepts a valid or empty range', () => {
    expect(dateRangeError('2020', '2021')).toBeNull()
    expect(dateRangeError('', '')).toBeNull()
    expect(dateRangeError('2020-01-01', '')).toBeNull()
  })

  it.each(['20', '2026-13', '2026-02-30', '2026-1-1', 'abcd', '0000'])('rejects %s', (text) => {
    expect(dateRangeError(text, '')).toMatch(/Enter each publication date/)
  })

  it('rejects a from date after the to date', () => {
    expect(dateRangeError('2022', '2021')).toMatch(/after the "to" date/)
    expect(dateRangeError('2021-06-02', '2021-06-01')).toMatch(/after the "to" date/)
  })

  it('allows the same year at both ends', () => {
    expect(dateRangeError('2021', '2021')).toBeNull()
  })
})

describe('cleanDateInput', () => {
  it('keeps only digits and dashes, at most ten characters', () => {
    expect(cleanDateInput('20a26/03-05')).toBe('202603-05')
    expect(cleanDateInput('2026-03-05-99')).toBe('2026-03-05')
  })
})

describe('formatBound', () => {
  it('formats a full date and a month', () => {
    expect(formatBound('2026-08-30')).toBe('Aug 30, 2026')
    expect(formatBound('2026-08')).toBe('Aug 2026')
  })

  it('returns anything else as typed', () => {
    expect(formatBound('2026')).toBe('2026')
    expect(formatBound('2026-02-30')).toBe('2026-02-30')
    expect(formatBound('  ')).toBe('')
  })
})
