import { describe, expect, it } from 'vitest'
import { EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive, sortPapers } from './paperFilter'

const filter = (patch) => ({ ...EMPTY_PAPER_FILTER, ...patch })

const papers = [
  {
    id: 1,
    title: 'Coral growth modeling',
    authors: ['Ada Lovelace'],
    venue: 'Coral Energy',
    year: 2021,
    abstract: 'Growth angle effects on reef output.',
    citation_count: 40,
    read: true,
  },
  { id: 2, title: 'Protein folding', authors: ['Grace Hopper'], year: 2019, abstract: '', citation_count: null },
  { id: 3, title: 'Cardiac imaging', authors: [], year: null, abstract: 'MRI methods.', relevance: 'relevant' },
]

const ids = (list) => list.map((p) => p.id)

describe('retracted papers', () => {
  const mixed = [
    { id: 1, title: 'Sound', authors: [], is_retracted: false },
    { id: 2, title: 'Withdrawn', authors: [], is_retracted: true },
    { id: 3, title: 'Unknown', authors: [] },
  ]

  it('are shown unless hidden', () => {
    expect(ids(filterPapers(mixed, filter()))).toEqual([1, 2, 3])
  })

  it('can be hidden, leaving papers whose status is unknown', () => {
    expect(ids(filterPapers(mixed, filter({ hideRetracted: true })))).toEqual([1, 3])
    expect(isPaperFilterActive(filter({ hideRetracted: true }))).toBe(true)
  })
})

describe('new papers', () => {
  const marked = [
    { id: 1, title: 'Old', authors: [], is_new: false },
    { id: 2, title: 'Fresh', authors: [], is_new: true },
    { id: 3, title: 'Unmarked', authors: [] },
  ]

  it('keeps only the papers the latest check added', () => {
    expect(ids(filterPapers(marked, filter({ newOnly: true })))).toEqual([2])
  })

  it('counts as an active filter and combines with the others', () => {
    expect(isPaperFilterActive(filter({ newOnly: true }))).toBe(true)
    expect(ids(filterPapers(marked, filter({ newOnly: true, query: 'old' })))).toEqual([])
  })

  it('shows everything when off', () => {
    expect(ids(filterPapers(marked, filter()))).toEqual([1, 2, 3])
  })
})

describe('isPaperFilterActive', () => {
  it('is false for the empty filter and for blank inputs', () => {
    expect(isPaperFilterActive(EMPTY_PAPER_FILTER)).toBe(false)
    expect(isPaperFilterActive(filter({ query: '   ', yearFrom: '', minCitations: '' }))).toBe(false)
  })

  it('is true when anything is set', () => {
    expect(isPaperFilterActive(filter({ query: 'x' }))).toBe(true)
    expect(isPaperFilterActive(filter({ yearTo: '2020' }))).toBe(true)
    expect(isPaperFilterActive(filter({ readState: 'read' }))).toBe(true)
    expect(isPaperFilterActive(filter({ relevance: 'neutral' }))).toBe(true)
    expect(isPaperFilterActive(filter({ missingAbstractOnly: true }))).toBe(true)
  })
})

describe('filterPapers', () => {
  it('returns the same list when nothing is active', () => {
    expect(filterPapers(papers, EMPTY_PAPER_FILTER)).toBe(papers)
  })

  it('needs every query term, case-insensitively, across title, authors, venue, year and abstract', () => {
    expect(ids(filterPapers(papers, filter({ query: 'GROWTH coral' })))).toEqual([1])
    expect(ids(filterPapers(papers, filter({ query: 'lovelace 2021' })))).toEqual([1])
    expect(ids(filterPapers(papers, filter({ query: 'growth protein' })))).toEqual([])
  })

  it('finds papers with a missing abstract', () => {
    expect(ids(filterPapers(papers, filter({ missingAbstractOnly: true })))).toEqual([2])
  })

  it('filters by read state', () => {
    expect(ids(filterPapers(papers, filter({ readState: 'read' })))).toEqual([1])
    expect(ids(filterPapers(papers, filter({ readState: 'unread' })))).toEqual([2, 3])
  })

  it('treats a missing relevance as neutral', () => {
    expect(ids(filterPapers(papers, filter({ relevance: 'neutral' })))).toEqual([1, 2])
    expect(ids(filterPapers(papers, filter({ relevance: 'relevant' })))).toEqual([3])
  })

  it('filters by year range and drops papers with no year', () => {
    expect(ids(filterPapers(papers, filter({ yearFrom: '2020' })))).toEqual([1])
    expect(ids(filterPapers(papers, filter({ yearTo: '2020' })))).toEqual([2])
    expect(ids(filterPapers(papers, filter({ yearFrom: '2019', yearTo: '2021' })))).toEqual([1, 2])
  })

  it('counts a missing citation count as zero', () => {
    expect(ids(filterPapers(papers, filter({ minCitations: '10' })))).toEqual([1])
    expect(ids(filterPapers(papers, filter({ minCitations: '0' })))).toEqual([1, 2, 3])
  })

  it('ignores a number field that is not a number', () => {
    expect(isPaperFilterActive(filter({ yearFrom: 'abc' }))).toBe(false)
  })
})

describe('sortPapers', () => {
  const list = [
    { id: 'a', year: 2020, publication_date: '2020-05-01', citation_count: 5 },
    { id: 'b', year: 2020, publication_date: '2020-11-01', citation_count: 50 },
    { id: 'c', year: 2022, citation_count: null },
    { id: 'd', citation_count: 1 },
  ]

  it('sorts newest first using the full date, falling back to the year', () => {
    expect(ids(sortPapers(list, 'date-desc'))).toEqual(['c', 'b', 'a', 'd'])
  })

  it('sorts oldest first and still puts undated papers last', () => {
    expect(ids(sortPapers(list, 'date-asc'))).toEqual(['a', 'b', 'c', 'd'])
  })

  it('sorts by citations and puts missing counts last in both directions', () => {
    expect(ids(sortPapers(list, 'citations-desc'))).toEqual(['b', 'a', 'd', 'c'])
    expect(ids(sortPapers(list, 'citations-asc'))).toEqual(['d', 'a', 'b', 'c'])
  })

  it('does not change the input array', () => {
    const copy = [...list]
    sortPapers(list, 'date-asc')
    expect(list).toEqual(copy)
  })
})
