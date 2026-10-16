import { describe, expect, it } from 'vitest'
import {
  POLL_FAST_MS,
  POLL_SLOW_MS,
  isWorking,
  jobActivity,
  jobsFor,
  pollDelay,
  progressSignature,
  progressText,
  sameJobs,
  statusSignature,
} from './jobs'

const job = (extra = {}) => ({ id: 1, kind: 'run_score', status: 'running', stop_requested: false, progress: {}, ...extra })

describe('pollDelay', () => {
  it('asks quickly while something is going on and slowly otherwise', () => {
    expect(pollDelay([job()])).toBe(POLL_FAST_MS)
    expect(pollDelay([job({ status: 'queued' })])).toBe(POLL_FAST_MS)
    expect(pollDelay([job({ status: 'completed' }), job({ id: 2, status: 'incomplete' })])).toBe(POLL_SLOW_MS)
    expect(pollDelay([])).toBe(POLL_SLOW_MS)
  })
})

describe('signatures', () => {
  it('the status signature changes when a job starts, is asked to stop, or ends', () => {
    const base = statusSignature([job({ status: 'queued' })])
    expect(statusSignature([job({ status: 'running' })])).not.toBe(base)
    expect(statusSignature([job({ status: 'running', stop_requested: true })])).not.toBe(statusSignature([job()]))
    expect(statusSignature([job({ status: 'completed' })])).not.toBe(statusSignature([job()]))
  })

  it('the status signature ignores progress, and the progress signature follows it', () => {
    const a = job({ progress: { done: 20 } })
    const b = job({ progress: { done: 40 } })
    expect(statusSignature([a])).toBe(statusSignature([b]))
    expect(progressSignature([a])).not.toBe(progressSignature([b]))
  })

  it('a finished job no longer counts toward progress', () => {
    expect(progressSignature([job({ status: 'completed', progress: { done: 5 } })])).toBe('')
  })
})

describe('progressText', () => {
  it('words grading, lookup and search progress', () => {
    expect(progressText(job({ progress: { done: 120, total: 600 } }))).toBe('120 of 600 graded')
    expect(progressText(job({ kind: 'find_abstracts', progress: { attempted: 5, total: 25 } }))).toBe('5 of 25 looked up')
    expect(
      progressText(job({ kind: 'dataset_search', progress: { stage: 'Searching the paper databases...', done: 2, total: 8 } })),
    ).toBe('Searching the paper databases... 2 of 8')
    expect(progressText(job({ kind: 'dataset_search', progress: { stage: 'Processing the topic...' } }))).toBe(
      'Processing the topic...',
    )
  })

  it('has nothing to say before there is progress, or for a finished search', () => {
    expect(progressText(job())).toBeNull()
    expect(progressText(null)).toBeNull()
    expect(progressText(job({ kind: 'dataset_search', progress: { stage: 'Done' } }))).toBeNull()
  })
})

describe('isWorking and jobActivity', () => {
  it('counts waiting, running and stopping items as working', () => {
    for (const state of ['queued', 'running', 'stopping']) expect(isWorking({ state })).toBe(true)
    for (const state of ['incomplete', 'completed']) expect(isWorking({ state })).toBe(false)
    expect(isWorking(null)).toBe(false)
  })

  it('names what each kind of job does', () => {
    expect(jobActivity(job({ kind: 'find_abstracts' }))).toBe('Looking up abstracts')
    expect(jobActivity(null)).toBeNull()
  })
})

describe('sameJobs and jobsFor', () => {
  it('sees two polls that say the same thing as the same list', () => {
    const a = [job({ progress: { done: 20 } })]
    expect(sameJobs(a, [job({ progress: { done: 20 } })])).toBe(true)
    expect(sameJobs(a, [job({ progress: { done: 40 } })])).toBe(false)
    expect(sameJobs(a, a)).toBe(true)
    expect(sameJobs([], [job()])).toBe(false)
  })

  it('picks out the jobs on one dataset or evaluation', () => {
    const list = [job({ id: 1, run_id: 5 }), job({ id: 2, run_id: 6 }), job({ id: 3, dataset_id: 5, run_id: null })]
    expect(jobsFor(list, 'run_id', 5).map((j) => j.id)).toEqual([1])
    expect(jobsFor(list, 'dataset_id', 5).map((j) => j.id)).toEqual([3])
    expect(jobsFor(list, 'run_id', 99)).toEqual([])
  })
})
