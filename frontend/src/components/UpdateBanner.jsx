import { useState } from 'react'
import { X } from 'lucide-react'
import { useUpdateNotice } from '../lib/updateCheck'

const BLUE = 'border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-900 dark:bg-blue-900/20 dark:text-blue-200'
const AMBER = 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200'

function ReleaseLink({ notice, children }) {
  if (!notice.link) return null
  return (
    <a href={notice.link} target="_blank" rel="noopener noreferrer" className="font-medium underline underline-offset-2">
      {children}
    </a>
  )
}

// The app checks for a newer signed version on its own and downloads it in the background. This says
// where that stands, and offers to install it. The link was checked by the server to be this project's
// release page, and again by updateNotice.
export default function UpdateBanner() {
  const { notice, dismiss, install } = useUpdateNotice()
  const [installing, setInstalling] = useState(false)
  const [error, setError] = useState('')
  if (!notice) return null

  async function installNow() {
    setInstalling(true)
    setError('')
    try {
      await install()
    } catch (err) {
      setError(err.message || 'The update could not be started.')
      setInstalling(false)
    }
  }

  const button = (label) => (
    <button
      type="button"
      onClick={installNow}
      disabled={installing}
      className="mt-2 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
    >
      {installing ? 'Starting...' : label}
    </button>
  )

  let tone = BLUE
  let body
  switch (notice.kind) {
    case 'downloading':
      body = <>Version {notice.latest} of Lit Review is downloading ({Math.round(notice.progress * 100)}%). You can keep working.</>
      break
    case 'ready':
      body = (
        <>
          Version {notice.latest} of Lit Review is ready to install (you have {notice.current}). Lit Review will finish what it
          is doing, then restart. Your datasets and settings are kept. <ReleaseLink notice={notice}>See what’s new</ReleaseLink>
          <br />
          {button('Install and restart')}
        </>
      )
      break
    case 'ready-auto':
      body = (
        <>
          Version {notice.latest} of Lit Review was downloaded and will be installed the next time you open Lit Review.{' '}
          <ReleaseLink notice={notice}>See what’s new</ReleaseLink>
          <br />
          {button('Restart now')}
        </>
      )
      break
    case 'applying':
      body = <>Installing version {notice.latest}. Lit Review is restarting and will open a new window; you can close this one.</>
      break
    case 'required':
      tone = AMBER
      body = (
        <>
          This version of Lit Review ({notice.current}) needs to be updated to {notice.latest}.{' '}
          {notice.text || 'It may no longer work correctly.'}{' '}
          {notice.state === 'staged' ? (
            <>
              The update is ready.
              <br />
              {button('Install and restart')}
            </>
          ) : notice.state === 'downloading' ? (
            <>It is downloading now.</>
          ) : (
            <ReleaseLink notice={notice}>Download version {notice.latest}</ReleaseLink>
          )}
        </>
      )
      break
    default:
      tone = AMBER
      body = (
        <>
          {notice.error || `Version ${notice.latest} could not be installed.`}{' '}
          <ReleaseLink notice={notice}>Download version {notice.latest} yourself</ReleaseLink>
        </>
      )
  }

  return (
    <div role="status" className={`mx-auto mt-4 flex max-w-3xl items-start gap-3 rounded-md border px-4 py-3 text-sm ${tone}`}>
      <p className="flex-1">
        {body}
        {error && <span className="mt-1 block text-red-600 dark:text-red-400">{error}</span>}
      </p>
      {notice.dismissible && (
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          className="shrink-0 rounded p-1 hover:bg-black/5 dark:hover:bg-white/10"
        >
          <X size={16} />
        </button>
      )}
    </div>
  )
}
