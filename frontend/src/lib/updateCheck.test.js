import { afterEach, describe, expect, it, vi } from 'vitest'
import { describeStatus, dismissalKey, getDismissed, pollDelay, shouldShow, updateNotice, POLL_FAST_MS, POLL_SLOW_MS } from './updateCheck'

afterEach(() => vi.unstubAllGlobals())

const link = 'https://github.com/colinpetree/lit-review/releases/tag/v0.2.0'
const status = (over = {}) => ({
  state: 'staged',
  current: '0.1.0',
  latest: '0.2.0',
  url: link,
  notice: '',
  required: false,
  progress: 1,
  error: '',
  auto_apply: false,
  ...over,
})

describe('updateNotice', () => {
  it('shows nothing when idle, unheard or without a version', () => {
    expect(updateNotice(null)).toBe(null)
    expect(updateNotice(status({ state: 'idle', latest: null }))).toBe(null)
    expect(updateNotice(status({ state: 'available' }))).toBe(null)
  })

  it('shows a download in progress', () => {
    expect(updateNotice(status({ state: 'downloading', progress: 0.4 }))).toMatchObject({ kind: 'downloading', progress: 0.4, dismissible: true })
  })

  it('offers to install when downloaded and automatic installing is off', () => {
    expect(updateNotice(status())).toMatchObject({ kind: 'ready', link })
  })

  it('says it installs itself when automatic installing is on', () => {
    expect(updateNotice(status({ auto_apply: true }))).toMatchObject({ kind: 'ready-auto' })
  })

  it('shows the restart as not dismissible', () => {
    expect(updateNotice(status({ state: 'applying' }))).toMatchObject({ kind: 'applying', dismissible: false })
  })

  it('shows a failed or unsupported install as a problem with the link', () => {
    expect(updateNotice(status({ state: 'failed', error: 'It did not work.' }))).toMatchObject({ kind: 'problem', error: 'It did not work.' })
    expect(updateNotice(status({ state: 'unsupported' }))).toMatchObject({ kind: 'problem' })
  })

  it('a required update cannot be dismissed, in any state it can be in', () => {
    for (const state of ['available', 'downloading', 'staged', 'failed', 'unsupported']) {
      expect(updateNotice(status({ state, required: true }))).toMatchObject({ kind: 'required', dismissible: false })
    }
  })

  it('required needs to be exactly true', () => {
    expect(updateNotice(status({ required: 'yes' }))).toMatchObject({ kind: 'ready' })
  })

  it('drops a link it cannot safely open', () => {
    expect(updateNotice(status({ url: 'javascript:alert(1)' })).link).toBe(null)
    expect(updateNotice(status({ url: null })).link).toBe(null)
  })
})

describe('shouldShow', () => {
  it('hides a dismissed notice for that version and kind only', () => {
    const notice = updateNotice(status())
    expect(shouldShow(notice, null)).toBe(true)
    expect(shouldShow(notice, dismissalKey(notice))).toBe(false)
    expect(shouldShow(updateNotice(status({ latest: '0.3.0' })), dismissalKey(notice))).toBe(true)
    expect(shouldShow(updateNotice(status({ auto_apply: true })), dismissalKey(notice))).toBe(true)
  })

  it('never hides what cannot be dismissed', () => {
    const notice = updateNotice(status({ required: true }))
    expect(shouldShow(notice, dismissalKey(notice))).toBe(true)
  })

  it('shows nothing for no notice', () => {
    expect(shouldShow(null, null)).toBe(false)
  })
})

describe('pollDelay', () => {
  it('is quick while downloading or restarting, slow otherwise', () => {
    expect(pollDelay({ state: 'downloading' })).toBe(POLL_FAST_MS)
    expect(pollDelay({ state: 'applying' })).toBe(POLL_FAST_MS)
    expect(pollDelay({ state: 'staged' })).toBe(POLL_SLOW_MS)
    expect(pollDelay(null)).toBe(POLL_SLOW_MS)
  })
})

describe('describeStatus', () => {
  it('describes each state in words', () => {
    expect(describeStatus(null)).toBe('Checking...')
    expect(describeStatus(status({ state: 'idle', latest: null }))).toBe('You have the latest version')
    expect(describeStatus(status({ state: 'downloading', progress: 0.5 }))).toContain('50%')
    expect(describeStatus(status({ auto_apply: true }))).toContain('next time you open')
    expect(describeStatus(status())).toContain('ready to install')
    expect(describeStatus(status({ state: 'failed', error: 'Nope' }))).toBe('Nope')
  })
})

describe('the remembered dismissal', () => {
  it('is read from storage', () => {
    vi.stubGlobal('localStorage', { getItem: () => '0.2.0:ready' })
    expect(getDismissed()).toBe('0.2.0:ready')
  })

  it('copes with storage that throws', () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
    })
    expect(getDismissed()).toBe(null)
  })
})
