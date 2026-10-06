import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  describeStatus,
  dismissalKey,
  getDismissed,
  getModalDismissed,
  hasRestarted,
  installedVersion,
  installsAtNextStart,
  isBannerNotice,
  modalKey,
  pollDelay,
  rememberModalDismissed,
  shouldOfferModal,
  shouldShow,
  updateNotice,
  POLL_FAST_MS,
  POLL_SLOW_MS,
} from './updateCheck'

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

  it('treats a required update like any other: quiet download, the same dialog, no special notice', () => {
    for (const state of ['available', 'downloading', 'staged', 'failed', 'unsupported']) {
      expect(updateNotice(status({ state, required: true }))?.kind).not.toBe('required')
    }
    expect(updateNotice(status({ state: 'downloading', required: true }))).toMatchObject({ kind: 'downloading' })
    expect(updateNotice(status({ required: true }))).toMatchObject({ kind: 'ready-auto' })
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

  it('never hides what cannot be dismissed (the restart)', () => {
    const notice = updateNotice(status({ state: 'applying' }))
    expect(shouldShow(notice, dismissalKey(notice))).toBe(true)
  })

  it('shows nothing for no notice', () => {
    expect(shouldShow(null, null)).toBe(false)
  })
})

describe('pollDelay', () => {
  it('is quick while a download or restart is under way', () => {
    for (const state of ['downloading', 'applying', 'available']) {
      expect(pollDelay({ state })).toBe(POLL_FAST_MS)
    }
  })

  it('is quick until the first check has finished, so a quiet download is not missed', () => {
    expect(pollDelay({ state: 'idle', checked_at: null, enabled: true })).toBe(POLL_FAST_MS)
    expect(pollDelay({ state: 'idle', checked_at: 1700000000, enabled: true })).toBe(POLL_SLOW_MS)
  })

  it('is slow where nothing is ever checked, when ready, and before anything is heard', () => {
    expect(pollDelay({ state: 'idle', checked_at: null, enabled: false })).toBe(POLL_SLOW_MS)
    expect(pollDelay({ state: 'staged' })).toBe(POLL_SLOW_MS)
    expect(pollDelay(null)).toBe(POLL_SLOW_MS)
  })

  it('is slow enough to be cheap but fast enough that the dialog is not minutes late', () => {
    expect(POLL_SLOW_MS).toBeLessThanOrEqual(60 * 1000)
  })
})

describe('describeStatus before the first check', () => {
  it('does not say "up to date" before the first check has finished', () => {
    expect(describeStatus(status({ state: 'idle', latest: null, checked_at: null, enabled: true }))).toBe('Checking for a new version...')
    expect(describeStatus(status({ state: 'idle', latest: null, checked_at: null, enabled: false }))).toBe(
      'Updates are only checked in the installed app',
    )
  })
})

describe('describeStatus', () => {
  it('describes each state in words', () => {
    expect(describeStatus(null)).toBe('Checking...')
    expect(describeStatus(status({ state: 'idle', latest: null, checked_at: 1 }))).toBe('You have the latest version')
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

describe('the "update ready" dialog', () => {
  const ready = status({ instance: 'run-1' })

  it('is keyed by this run of the app and the version', () => {
    expect(modalKey(ready)).toBe('run-1:0.2.0')
    expect(modalKey(status({ instance: undefined }))).toBe(null)
    expect(modalKey(status({ instance: 'run-1', latest: null }))).toBe(null)
    expect(modalKey(null)).toBe(null)
  })

  it('is offered once an update has been downloaded and the person installs updates themselves', () => {
    expect(shouldOfferModal(ready, null)).toBe(true)
  })

  it('is not offered to someone whose updates install on their own at the next start', () => {
    expect(shouldOfferModal({ ...ready, auto_apply: true }, null)).toBe(false)
  })

  it('is offered for a required update even to someone with automatic installing on', () => {
    expect(shouldOfferModal({ ...ready, required: true }, null)).toBe(true)
    expect(shouldOfferModal({ ...ready, required: true, auto_apply: true }, null)).toBe(true)
    expect(shouldOfferModal({ ...ready, required: true, state: 'downloading' }, null)).toBe(false)
  })

  it('knows which updates install on their own at the next start, and which do not', () => {
    expect(installsAtNextStart(ready)).toBe(false)
    expect(installsAtNextStart({ ...ready, auto_apply: true })).toBe(true)
    expect(installsAtNextStart({ ...ready, required: true })).toBe(true)
    expect(installsAtNextStart({ ...ready, required: 'yes', auto_apply: 'yes' })).toBe(false)
    expect(installsAtNextStart(null)).toBe(false)
  })

  it('is not offered while nothing is downloaded, or while it is still downloading', () => {
    for (const state of ['idle', 'available', 'downloading', 'applying', 'failed', 'unsupported']) {
      expect(shouldOfferModal({ ...ready, state }, null)).toBe(false)
    }
    expect(shouldOfferModal(null, null)).toBe(false)
  })

  it('stays closed once dismissed in this run, and comes back for the next start or a newer version', () => {
    const key = modalKey(ready)
    expect(shouldOfferModal(ready, key)).toBe(false)
    expect(shouldOfferModal({ ...ready, instance: 'run-2' }, key)).toBe(true)
    expect(shouldOfferModal({ ...ready, latest: '0.3.0' }, key)).toBe(true)
  })

  it('is not offered when the app did not say which run it is', () => {
    expect(shouldOfferModal({ ...ready, instance: undefined }, null)).toBe(false)
  })

  it('remembers a dismissal for this tab, and copes with storage that throws', () => {
    const store = {}
    vi.stubGlobal('sessionStorage', {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => {
        store[k] = v
      },
    })
    expect(getModalDismissed()).toBe(null)
    rememberModalDismissed('run-1:0.2.0')
    expect(getModalDismissed()).toBe('run-1:0.2.0')

    vi.stubGlobal('sessionStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    })
    expect(getModalDismissed()).toBe(null)
    expect(() => rememberModalDismissed('x')).not.toThrow()
  })
})

describe('what is shown at the top of the page', () => {
  it('keeps the download quiet, and leaves the finished one to the dialog', () => {
    expect(isBannerNotice(updateNotice(status({ state: 'downloading', progress: 0.4 })))).toBe(false)
    expect(isBannerNotice(updateNotice(status()))).toBe(false)
    expect(isBannerNotice(updateNotice(status({ auto_apply: true })))).toBe(false)
  })

  it('still shows what needs attention: a failure', () => {
    expect(isBannerNotice(updateNotice(status({ state: 'failed', error: 'No.' })))).toBe(true)
  })

  it('leaves the restart to the "Installing the update" dialog', () => {
    expect(isBannerNotice(updateNotice(status({ state: 'applying' })))).toBe(false)
  })

  it('keeps a required update as quiet as any other, while it downloads and once it is ready', () => {
    expect(isBannerNotice(updateNotice(status({ required: true, state: 'downloading' })))).toBe(false)
    expect(isBannerNotice(updateNotice(status({ required: true })))).toBe(false)
  })

  it('still shows a required update that could not be installed, with the link to get it by hand', () => {
    const notice = updateNotice(status({ required: true, state: 'failed', error: 'It did not work.' }))
    expect(isBannerNotice(notice)).toBe(true)
    expect(notice).toMatchObject({ kind: 'problem', error: 'It did not work.' })
  })

  it('shows nothing when there is no notice', () => {
    expect(isBannerNotice(null)).toBe(false)
  })
})

describe('installedVersion', () => {
  it('is the version the helper just installed, until it has been seen', () => {
    expect(installedVersion({ installed_version: '0.2.0' })).toBe('0.2.0')
  })

  it('is null for an ordinary start, a missing status or a bad value', () => {
    expect(installedVersion({ installed_version: null })).toBe(null)
    expect(installedVersion({})).toBe(null)
    expect(installedVersion(null)).toBe(null)
    expect(installedVersion({ installed_version: '' })).toBe(null)
    expect(installedVersion({ installed_version: 5 })).toBe(null)
  })
})

describe('hasRestarted', () => {
  it('is true once the app answers as a different run than the one the install began with', () => {
    expect(hasRestarted('a', { instance: 'b' })).toBe(true)
  })

  it('is false for the same run, before an install, or before the app answers', () => {
    expect(hasRestarted('a', { instance: 'a' })).toBe(false)
    expect(hasRestarted(null, { instance: 'b' })).toBe(false)
    expect(hasRestarted('a', null)).toBe(false)
    expect(hasRestarted('a', {})).toBe(false)
  })
})
