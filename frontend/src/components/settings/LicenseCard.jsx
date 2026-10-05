import { useState } from 'react'
import { Card } from '../ui'
import LicenseModal from '../LicenseModal'

// The license, and what leaves this computer when the app is used, in one place a user can
// find without the download folder.
export default function LicenseCard() {
  const [open, setOpen] = useState(false)
  return (
    <Card className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">License</p>
        <p className="text-xs text-gray-400">
          <a
            href="https://github.com/colinpetree/lit-review"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 underline-offset-2 hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
          >
            Lit Review
          </a>{' '}
          is free to use for any purpose, including at work. You may not use its code to offer a competing commercial
          product or service. Copyright 2026 Colin Petree.
        </p>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
        >
          View full license
        </button>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Notices</p>
        <ul className="flex list-disc flex-col gap-1.5 pl-4 text-xs text-gray-400">
          <li>
            Your research question, grading criteria, and paper titles and abstracts are sent to the AI company you
            choose.
          </li>
          <li>
            The search queries are sent to the research databases you search, and a paper’s DOI is used to look up a
            missing abstract.
          </li>
          <li>
            The AI company and each research database bill or limit you under their own terms. Scores and rationales are AI
            judgments and can be wrong. Read the papers before relying on them.
          </li>
          <li>
            Nothing is sent to the author of Lit Review. Your data stays on this computer, apart from the above.
          </li>
        </ul>
      </div>

      {open && <LicenseModal onClose={() => setOpen(false)} />}
    </Card>
  )
}
