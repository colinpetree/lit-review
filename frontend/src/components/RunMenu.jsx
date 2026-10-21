import { useState } from 'react'
import { Pencil, Play, Square, Trash2 } from 'lucide-react'
import MoreMenu from './MoreMenu'
import ConfirmModal from './ConfirmModal'
import RenameModal from './RenameModal'
import { patchJson } from '../lib/api'
import { useJobs } from './JobsProvider'
import { isWorking } from '../lib/jobs'

const MAX_RUN_NAME_CHARS = 120 // matches MAX_RUN_NAME_CHARS in db.py

// The more-horizontal menu for an analysis run: Rename (a modal that saves the
// new name, then calls onRenamed(name)) and, when onDelete is given, Delete
// behind a confirmation. A run being graded (or waiting to be) can be stopped here, and one
// with papers still ungraded started again; `onError` hears why that failed.
export default function RunMenu({ run, onRenamed, onDelete, onError, className, floating = false, extraItems = [] }) {
  const [modal, setModal] = useState(null) // 'rename' | 'delete' | null
  const { stopJob, startJob } = useJobs()

  const report = (err) => onError?.(err.message)
  const items = [{ label: 'Rename', icon: Pencil, onClick: () => setModal('rename') }, ...extraItems]
  if (run.job && (run.state === 'queued' || run.state === 'running')) {
    items.push({ label: 'Stop', icon: Square, onClick: () => stopJob(run.job.id).catch(report) })
  } else if (run.state === 'incomplete') {
    items.push({
      label: 'Resume',
      icon: Play,
      // A run its spending limit stopped has that limit raised by its starting amount first (server side).
      onClick: () => startJob({ kind: 'run_score', run_id: run.id, extend_limit: true }).catch(report),
    })
  }
  if (onDelete) items.push({ label: 'Delete', icon: Trash2, danger: true, onClick: () => setModal('delete') })

  return (
    <>
      <MoreMenu className={className} floating={floating} items={items} />
      {modal === 'rename' ? (
        <RenameModal
          title="Rename run"
          initialName={run.name ?? ''}
          maxLength={MAX_RUN_NAME_CHARS}
          onSave={async (name) => {
            const saved = await patchJson(`/api/analysis-runs/${run.id}`, { name })
            onRenamed(saved.name)
          }}
          onClose={() => setModal(null)}
        />
      ) : null}
      {modal === 'delete' ? (
        <ConfirmModal
          title="Delete this result run?"
          message={`${
            isWorking(run) ? 'Grading will be stopped. ' : ''
          }This moves the run and its grades out of your results into Deleted Items (in Settings, under Your Data), where you can restore it or delete it permanently. The papers and datasets are not affected.`}
          confirmLabel="Delete"
          busyLabel="Deleting..."
          danger
          onConfirm={onDelete}
          onClose={() => setModal(null)}
        />
      ) : null}
    </>
  )
}
