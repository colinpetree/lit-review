import { useState } from 'react'
import { Download } from 'lucide-react'
import { Card } from '../ui'
import EditableCardHeader from '../EditableCardHeader'
import Toggle from '../Toggle'
import useSavedState from '../../lib/useSavedState'
import { useUpdateCheckEnabled } from '../../lib/updateCheck'

// Whether the app asks GitHub if a newer version has been published. A per-browser
// setting like PubMed's, with the same Edit/Save flow.
export default function UpdatesCard() {
  const [enabled, setEnabled] = useUpdateCheckEnabled()
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
        title="New versions"
        icon={Download}
        description="When you open Lit Review, it asks GitHub (where new versions are published) whether one is available, and tells you if so. Only the program’s name and version are sent, nothing about you or your work, and it is asked at most once a day. Updating means downloading the new version yourself; your data is kept."
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={draft !== enabled}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={() => commit(async () => setEnabled(draft))}
      />

      {editing ? (
        <Toggle label="Check for new versions" checked={draft} onChange={setDraft} />
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">Status</p>
          <p className="text-sm">
            {enabled ? (
              <span className="font-medium text-[#30cf43]">Checking</span>
            ) : (
              <span className="text-gray-400">Not checking</span>
            )}
          </p>
        </div>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}
