import { useState } from 'react'
import { Database } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card } from '../ui'
import ConfirmModal from '../ConfirmModal'
import { downloadBackup, restoreBackup } from '../../lib/dataFiles'

// Backing up and restoring everything the app has stored (not the API keys), and the way
// to the trash. A restore replaces all current data, so it is confirmed first and the
// replaced data is kept by the server as a file.
export default function DataCard() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [picked, setPicked] = useState(null) // the file chosen to restore, awaiting confirmation
  const [restored, setRestored] = useState(null) // the server's answer after a restore

  async function backup() {
    setError(null)
    setBusy(true)
    try {
      await downloadBackup()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const buttonClass =
    'rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50'

  return (
    <Card className="flex flex-col gap-5">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-800 [--icon-nudge:-1px]">
        <Database size={18} className="shrink-0" />
        Backup and restore
      </h2>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Backup</p>
        <p className="text-xs text-gray-400">
          One file holding every dataset, paper, result run and prompt, and what you have spent. Your API keys are not
          included: they stay on this computer and are never backed up.
        </p>
        <button type="button" onClick={backup} disabled={busy} className={`${buttonClass} self-start`}>
          {busy ? 'Preparing…' : 'Download backup'}
        </button>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Restore</p>
        <p className="text-xs text-gray-400">
          Replaces everything now in the app with what is in a backup file. Your current data is first kept as a
          file in the app's data folder, so a restore can be undone.
        </p>
        <label className={`${buttonClass} cursor-pointer self-start`}>
          Restore from backup…
          <input
            type="file"
            accept=".db,application/octet-stream"
            className="sr-only"
            onChange={(e) => {
              setError(null)
              setRestored(null)
              setPicked(e.target.files?.[0] ?? null)
              // Choosing the same file again later must still fire a change.
              e.target.value = ''
            }}
          />
        </label>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Deleted items</p>
        <p className="text-xs text-gray-400">
          Datasets, prompts and result runs you delete are kept, hidden from the rest of the app, until you remove them for good.
          Bring one back, or delete it permanently.
        </p>
        <Link
          to="/settings/data/trash"
          className="self-start text-sm text-blue-600 underline-offset-2 hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
        >
          View or restore deleted items
        </Link>
      </div>

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
      {restored ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-gray-800">{restored.message}</p>
          <p className="text-sm text-gray-600">
            Any other Lit Review tab or window is still showing the old data: reload it.
          </p>
          <button type="button" onClick={() => window.location.reload()} className={`${buttonClass} self-start`}>
            Reload this page
          </button>
        </div>
      ) : null}

      {picked ? (
        <ConfirmModal
          title="Replace all your data with this backup?"
          message={`Everything now in Lit Review (datasets, papers, results, prompts and spending history) will be replaced by the contents of "${picked.name}". Your current data is kept as a file in the app's data folder first. Nothing else can be done in the app while it is restored. Your API keys are not affected.`}
          confirmLabel="Replace my data"
          busyLabel="Restoring..."
          danger
          onConfirm={async () => {
            setRestored(await restoreBackup(picked))
          }}
          onClose={() => setPicked(null)}
        />
      ) : null}
    </Card>
  )
}
