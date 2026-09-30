import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import MoreMenu from './MoreMenu'
import ConfirmModal from './ConfirmModal'

// A more-horizontal menu whose only action is Delete, behind a confirmation
// modal. For menus with more actions, use MoreMenu + ConfirmModal directly.
export default function DeleteMenu({ title, message, onConfirm, className }) {
  const [confirming, setConfirming] = useState(false)

  return (
    <>
      <MoreMenu
        className={className}
        items={[{ label: 'Delete', icon: Trash2, danger: true, onClick: () => setConfirming(true) }]}
      />
      {confirming ? (
        <ConfirmModal
          title={title}
          message={message}
          confirmLabel="Delete"
          busyLabel="Deleting..."
          danger
          onConfirm={onConfirm}
          onClose={() => setConfirming(false)}
        />
      ) : null}
    </>
  )
}
