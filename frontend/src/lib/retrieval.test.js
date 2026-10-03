import { describe, expect, it } from 'vitest'
import { groupBySource, hitsText, summarizeRetrieval } from './retrieval'

const entry = (changes = {}) => ({
  source: 'openalex',
  query: 'coral reef',
  total: 120,
  fetched: 120,
  kept: 118,
  capped: null,
  capped_by: null,
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

  it('gives no reason for the plain limit: the numbers beside each search say it', () => {
    const limited = (query) =>
      entry({ query, total: 900, fetched: 100, capped: `OpenAlex matched 900 papers; the 100 most relevant were kept.`, capped_by: 'limit' })
    const summary = summarizeRetrieval([limited('a'), limited('b'), limited('c'), entry()])
    expect(summary.complete).toBe(false)
    expect(summary.incomplete).toHaveLength(3)
    expect(summary.reasons).toEqual([])
  })

  it('lists each distinct reason from a source limit once', () => {
    const source = 'Semantic Scholar will not return more than 1,000 papers for one search.'
    const summary = summarizeRetrieval([
      entry({ capped: source, capped_by: 'source' }),
      entry({ capped: source, capped_by: 'source', query: 'reef' }),
      entry({ capped: 'PubMed returned only 5 of the 9 papers it reports.', capped_by: 'source' }),
      entry(),
    ])
    expect(summary.reasons).toEqual([source, 'PubMed returned only 5 of the 9 papers it reports.'])
  })

  it('leaves out a note saved before the cause was recorded, such as the old long sentence', () => {
    const old = 'OpenAlex matched 368 papers; the 100 most relevant were kept. To see others, narrow the question.'
    const summary = summarizeRetrieval([entry({ capped: old, capped_by: undefined })])
    expect(summary.complete).toBe(false)
    expect(summary.reasons).toEqual([])
  })
})

describe('hitsText', () => {
  it('says how many were kept of how many matched', () => {
    expect(hitsText(entry({ total: 368, fetched: 100 }))).toBe('100 of 368')
    expect(hitsText(entry({ total: 24, fetched: 24 }))).toBe('24 of 24')
    expect(hitsText(entry({ total: 3200, fetched: 1000 }))).toBe('1,000 of 3,200')
  })

  it('says only how many were kept when the source does not say how many match', () => {
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
