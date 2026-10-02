import { useState } from 'react'
import { Pencil } from 'lucide-react'
import MoreMenu from './MoreMenu'
import RenameModal from './RenameModal'
import { patchJson } from '../lib/api'

const MAX_DATASET_NAME_CHARS = 120 // matches MAX_DATASET_NAME_CHARS in app.py

// The more-horizontal menu for a dataset: Rename, a modal that saves the new
// name, then calls onRenamed(name).
export default function DatasetMenu({ dataset, onRenamed, className }) {
  const [renaming, setRenaming] = useState(false)

  return (
    <>
      <MoreMenu className={className} items={[{ label: 'Rename', icon: Pencil, onClick: () => setRenaming(true) }]} />
      {renaming ? (
        <RenameModal
          title="Rename dataset"
          initialName={dataset.name}
          maxLength={MAX_DATASET_NAME_CHARS}
          onSave={async (name) => {
            const saved = await patchJson(`/api/datasets/${dataset.id}`, { name })
            onRenamed(saved.name)
          }}
          onClose={() => setRenaming(false)}
        />
      ) : null}
    </>
  )
}
