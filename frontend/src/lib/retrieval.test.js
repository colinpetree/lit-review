import { describe, expect, it } from 'vitest'
import { groupBySource, hitsText, summarizeRetrieval } from './retrieval'

const entry = (changes = {}) => ({
  source: 'openalex',
  query: 'coral reef',
  total: 120,
  fetched: 120,
  kept: 118,
  capped: null,
  ...changes,
})

describe('summarizeRetrieval', () => {
  it('is null when nothing was recorded', () => {
    expect(summarizeRetrieval(null)).toBeNull()
    expect(summarizeRetrieval(undefined)).toBeNull()
    expect(summarizeRetrieval([])).toBeNull()
  })

  it('is complete when no search was capped', () => {
    expect(summarizeRetrieval([entry(), entry({ query: 'reef' })])).toMatchObject({ complete: true, reasons: [] })
  })

  it('lists each distinct reason once', () => {
    const limit = 'PubMed will not return more than 10,000 papers for one search.'
    const summary = summarizeRetrieval([
      entry({ capped: limit }),
      entry({ capped: limit, query: 'reef' }),
      entry({ capped: 'Stopped at 10,000.' }),
      entry(),
    ])
    expect(summary.complete).toBe(false)
    expect(summary.incomplete).toHaveLength(3)
    expect(summary.reasons).toEqual([limit, 'Stopped at 10,000.'])
  })
})

describe('hitsText', () => {
  it('shows fetched of total', () => {
    expect(hitsText(entry({ total: 3200, fetched: 1000 }))).toBe('1,000 of 3,200')
    expect(hitsText(entry())).toBe('120 of 120')
  })

  it('shows only what was fetched when the source does not say how many match', () => {
    expect(hitsText(entry({ total: null, fetched: 40 }))).toBe('40')
  })
})

describe('groupBySource', () => {
  it('groups in the order sources first appear', () => {
    const groups = groupBySource([
      entry({ source: 'openalex' }),
      entry({ source: 'pubmed' }),
      entry({ source: 'openalex', query: 'reef' }),
    ])
    expect(groups.map((g) => [g.source, g.entries.length])).toEqual([
      ['openalex', 2],
      ['pubmed', 1],
    ])
  })

  it('is empty for nothing', () => {
    expect(groupBySource(null)).toEqual([])
  })
})
