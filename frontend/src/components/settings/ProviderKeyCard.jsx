import { useState } from 'react'
import { Card } from '../ui'
import EditableCardHeader from '../EditableCardHeader'
import useSavedState from '../../lib/useSavedState'

// Stands in for a saved key (the real value is never sent to the browser), long
// enough that the field looks filled.
const MASKED_KEY = '•'.repeat(48)

export default function ProviderKeyCard({
  provider,
  label,
  icon,
  keyName: keyNameOverride,
  description,
  keyUrl,
  keyPlaceholder = 'API key...',
  hasKey,
  onSave,
  onDelete,
}) {
  const [input, setInput] = useState('')
  const [removing, setRemoving] = useState(false)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  const isDirty = removing || input.trim().length > 0
  // Named after the key's own type when the company has more than one kind.
  const keyName = keyNameOverride ?? `${label} API Key`
  const article = /^[aeiou]/i.test(keyName) ? 'an' : 'a'

  function cancel() {
    setInput('')
    setRemoving(false)
    setEditing(false)
    setError('')
  }

  function handleSave() {
    commit(async () => {
      if (removing) {
        await onDelete(provider)
      } else {
        await onSave(provider, input)
      }
      setInput('')
      setRemoving(false)
    })
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title={label}
        icon={icon}
        description={description}
        linkUrl={keyUrl}
        linkLabel={`Get ${article} ${keyName}`}
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={isDirty}
        onEdit={() => setEditing(true)}
        onCancel={cancel}
        onSave={handleSave}
      />

      {editing ? (
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-gray-700">{keyName}</label>
          <input
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={removing}
            placeholder={hasKey ? MASKED_KEY : keyPlaceholder}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-800 w-full disabled:bg-gray-50 disabled:text-gray-400"
          />
          {hasKey && !removing && (
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-400">Currently set, enter a new value to replace it.</p>
              <button
                type="button"
                onClick={() => {
                  setRemoving(true)
                  setInput('')
                }}
                className="text-xs text-red-600 dark:text-red-400 hover:underline"
              >
                Remove saved key
              </button>
            </div>
          )}
          {removing && (
            <p className="text-xs text-red-600 dark:text-red-400">
              Key will be removed when you save.{' '}
              <button type="button" onClick={() => setRemoving(false)} className="underline">
                Undo
              </button>
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">{keyName}</p>
          {hasKey ? <p className="truncate text-sm text-gray-800">{MASKED_KEY}</p> : <p className="text-sm text-gray-400">Not set</p>}
        </div>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}
