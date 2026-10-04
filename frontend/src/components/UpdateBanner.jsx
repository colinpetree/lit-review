import { X } from 'lucide-react'
import { useUpdateNotice } from '../lib/updateCheck'

// A newer Lit Review has been published. The app is updated by downloading the new
// version, so this is only a notice with one link (the link was checked by the
// server to be this project's release page, and again by shouldShowUpdate).
export default function UpdateBanner() {
  const { notice, dismiss } = useUpdateNotice()
  if (!notice) return null
  return (
    <div
      role="status"
      className="mx-auto mt-4 flex max-w-3xl items-start gap-3 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900 dark:border-blue-900 dark:bg-blue-900/20 dark:text-blue-200"
    >
      <p className="flex-1">
        Version {notice.latest} of Lit Review is available (you have {notice.current}).{' '}
        <a
          href={notice.url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium underline underline-offset-2"
        >
          See what’s new and download it
        </a>
        . Your datasets and settings are kept when you update.
      </p>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="shrink-0 rounded p-1 text-blue-700 hover:bg-blue-100 dark:text-blue-300 dark:hover:bg-blue-900/40"
      >
        <X size={16} />
      </button>
    </div>
  )
}
