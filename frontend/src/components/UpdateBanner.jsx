import { useState } from 'react'
import { X } from 'lucide-react'
import { dismissalKey, getDismissed, isBannerNotice, rememberDismissed, shouldShow, updateNotice } from '../lib/updateCheck'
import { useUpdates } from './UpdateProvider'

const AMBER = 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200'

function ReleaseLink({ notice, children }) {
  if (!notice.link) return null
  return (
    <a href={notice.link} target="_blank" rel="noopener noreferrer" className="font-medium underline underline-offset-2">
      {children}
    </a>
  )
}

// What needs attention about updates, at the top of the page: one that could not be installed.
// A download in progress is NOT here (it is quiet; Settings shows its progress), nor is the restart (the
// "Installing the update" dialog says it), and neither is a finished one waiting: the "update ready" dialog
// (UpdateModal) offers it, and Settings keeps the same Install update button.
// The link was checked by the server to be this project's release page, and again by updateNotice.
export default function UpdateBanner() {
  const { status } = useUpdates()
  const [dismissed, setDismissed] = useState(getDismissed)
  const notice = updateNotice(status)
  if (!isBannerNotice(notice) || !shouldShow(notice, dismissed)) return null

  function dismiss() {
    rememberDismissed(dismissalKey(notice))
    setDismissed(dismissalKey(notice))
  }

  return (
    <div role="status" className={`mx-auto mt-4 flex max-w-3xl items-start gap-3 rounded-md border px-4 py-3 text-sm ${AMBER}`}>
      <p className="flex-1">
        {notice.error || `Version ${notice.latest} could not be installed.`}{' '}
        <ReleaseLink notice={notice}>Download version {notice.latest} yourself</ReleaseLink>
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
