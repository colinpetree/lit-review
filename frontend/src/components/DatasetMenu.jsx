import { useState } from 'react'
import { Pencil, Play, Square, Trash2 } from 'lucide-react'
import MoreMenu from './MoreMenu'
import ConfirmModal from './ConfirmModal'
import RenameModal from './RenameModal'
import { patchJson } from '../lib/api'
import { useJobs } from './JobsProvider'
import { isWorking } from '../lib/jobs'

const MAX_DATASET_NAME_CHARS = 120 // matches MAX_DATASET_NAME_CHARS in app.py

// The more-horizontal menu for a dataset: Rename (a modal that saves the new
// name, then calls onRenamed(name)) and, when onDelete is given, Delete behind
// a confirmation. A dataset with work going on (its search, a check for new papers, an
// abstract lookup) can be stopped here, and an unfinished search resumed; `onError` hears
// why that failed.
export default function DatasetMenu({ dataset, onRenamed, onDelete, onError, className, extraItems = [] }) {
  const [modal, setModal] = useState(null) // 'rename' | 'delete' | null
  const { stopJob, resumeJob } = useJobs()

  const report = (err) => onError?.(err.message)
  const items = [{ label: 'Rename', icon: Pencil, onClick: () => setModal('rename') }, ...extraItems]
  if (dataset.job && (dataset.state === 'queued' || dataset.state === 'running')) {
    items.push({ label: 'Stop', icon: Square, onClick: () => stopJob(dataset.job.id).catch(report) })
  } else if (dataset.job && dataset.state === 'incomplete') {
    items.push({ label: 'Resume', icon: Play, onClick: () => resumeJob(dataset.job.id).catch(report) })
  }
  if (onDelete) items.push({ label: 'Delete', icon: Trash2, danger: true, onClick: () => setModal('delete') })

  return (
    <>
      <MoreMenu className={className} items={items} />
      {modal === 'rename' ? (
        <RenameModal
          title="Rename dataset"
          initialName={dataset.name}
          maxLength={MAX_DATASET_NAME_CHARS}
          onSave={async (name) => {
            const saved = await patchJson(`/api/datasets/${dataset.id}`, { name })
            onRenamed(saved.name)
          }}
          onClose={() => setModal(null)}
        />
      ) : null}
      {modal === 'delete' ? (
        <ConfirmModal
          title="Delete this dataset?"
          message={`This removes the dataset from your list${
            isWorking(dataset) ? ' and stops the work going on for it' : ''
          }. Past result runs that used it and the papers themselves are not deleted.`}
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
