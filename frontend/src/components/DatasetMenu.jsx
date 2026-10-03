import { useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import MoreMenu from './MoreMenu'
import ConfirmModal from './ConfirmModal'
import RenameModal from './RenameModal'
import { patchJson } from '../lib/api'

const MAX_DATASET_NAME_CHARS = 120 // matches MAX_DATASET_NAME_CHARS in app.py

// The more-horizontal menu for a dataset: Rename (a modal that saves the new
// name, then calls onRenamed(name)) and, when onDelete is given, Delete behind
// a confirmation.
export default function DatasetMenu({ dataset, onRenamed, onDelete, className }) {
  const [modal, setModal] = useState(null) // 'rename' | 'delete' | null

  const items = [{ label: 'Rename', icon: Pencil, onClick: () => setModal('rename') }]
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
          message="This removes the dataset from your list. Past result runs that used it and the papers themselves are not deleted."
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
