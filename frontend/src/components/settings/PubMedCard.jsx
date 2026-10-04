import { useState } from 'react'
import { Card } from '../ui'
import EditableCardHeader from '../EditableCardHeader'
import Toggle from '../Toggle'
import { PubMedIcon } from '../ProviderIcons'
import useSavedState from '../../lib/useSavedState'
import { usePubMedEnabled } from '../../lib/pubmedSetting'

// PubMed needs no key, so its card is an on/off switch for offering it on
// Discover Papers (on by default), with the same Edit/Save flow as the key cards.
export default function PubMedCard() {
  const [enabled, setEnabled] = usePubMedEnabled()
  const [draft, setDraft] = useState(enabled)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  function startEditing() {
    setDraft(enabled)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="PubMed"
        icon={PubMedIcon}
        description="Medical and health literature from the US National Library of Medicine. Free, no key needed. Turn it off if you don’t want it offered on Discover Papers."
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={draft !== enabled}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={() => commit(async () => setEnabled(draft))}
      />

      {editing ? (
        <Toggle label="Offer PubMed as a paper source" checked={draft} onChange={setDraft} />
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">Status</p>
          <p className="text-sm">
            {enabled ? (
              <span className="font-medium text-[#30cf43]">Enabled</span>
            ) : (
              <span className="text-gray-400">Disabled</span>
            )}
          </p>
        </div>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}
