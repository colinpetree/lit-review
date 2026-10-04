import { useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import MoreMenu from './MoreMenu'
import ConfirmModal from './ConfirmModal'
import RenameModal from './RenameModal'
import { patchJson } from '../lib/api'

const MAX_RUN_NAME_CHARS = 120 // matches MAX_RUN_NAME_CHARS in db.py

// The more-horizontal menu for an analysis run: Rename (a modal that saves the
// new name, then calls onRenamed(name)) and, when onDelete is given, Delete
// behind a confirmation.
export default function RunMenu({ run, onRenamed, onDelete, className, extraItems = [] }) {
  const [modal, setModal] = useState(null) // 'rename' | 'delete' | null

  const items = [{ label: 'Rename', icon: Pencil, onClick: () => setModal('rename') }, ...extraItems]
  if (onDelete) items.push({ label: 'Delete', icon: Trash2, danger: true, onClick: () => setModal('delete') })

  return (
    <>
      <MoreMenu className={className} items={items} />
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
          message="This moves the run and its scores out of your results into Deleted Items (in Settings, under Your Data), where you can restore it or delete it permanently. The papers and datasets are not affected."
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
