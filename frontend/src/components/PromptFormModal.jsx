import { useState } from 'react'
import Modal from './Modal'
import AutoGrowTextarea from './AutoGrowTextarea'

const fieldClass =
  'mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm'

// Create/edit dialog for a scoring prompt: a title and the research question
// (the description the judge scores against). onSave may be async and throws
// on failure, which is shown in the dialog.
export default function PromptFormModal({ heading, initial, onSave, onClose }) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSave({ name: name.trim(), description: description.trim() })
      onClose()
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Modal title={heading} onClose={onClose} busy={busy}>
      <form onSubmit={submit} className="mt-4 flex flex-col gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700">Title</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            autoFocus
            className={fieldClass}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700">Research question</label>
          <AutoGrowTextarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={5}
            maxLength={4000}
            placeholder="Precisely what should a paper show to be relevant?"
            className={fieldClass}
          />
        </div>
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
        <div className="flex justify-end gap-2">
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
            disabled={busy || !name.trim() || !description.trim()}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? 'Saving...' : 'Save'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
