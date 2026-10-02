import { useState } from 'react'
import Modal from './Modal'

// Dialog with one text field holding the current name. onSave(name) may be
// async; a failure (a name that is already taken, for example) is shown in the
// dialog so the user can fix it, and success closes it.
export default function RenameModal({ title, initialName, maxLength, onSave, onClose }) {
  const [name, setName] = useState(initialName)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const trimmed = name.trim()

  const save = async (e) => {
    e.preventDefault()
    if (!trimmed) return
    if (trimmed === initialName) {
      onClose()
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onSave(trimmed)
      onClose()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose} busy={busy} closeOnBackdrop={false}>
      <form onSubmit={save}>
        <input
          autoFocus
          onFocus={(e) => e.target.select()}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={maxLength}
          aria-label="Name"
          disabled={busy}
          className="mt-4 w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-800"
        />
        {error ? <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !trimmed}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? 'Saving...' : 'Rename'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
