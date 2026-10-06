import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Card } from '../ui'
import EditableCardHeader from '../EditableCardHeader'
import Toggle from '../Toggle'
import useSavedState from '../../lib/useSavedState'
import { checkNow, describeStatus, fetchUpdateSettings, saveAutoApply, useUpdateStatus } from '../../lib/updateCheck'

// Lit Review always checks GitHub for a newer version and downloads it in the background (the AI
// models it uses change, so an old version can stop working). The one choice is whether a downloaded
// version installs itself the next time the app is opened, or waits for the user to press Install.
export default function UpdatesCard() {
  const { status, refresh } = useUpdateStatus()
  const [auto, setAuto] = useState(null)
  const [draft, setDraft] = useState(false)
  const [checking, setChecking] = useState(false)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  useEffect(() => {
    let cancelled = false
    fetchUpdateSettings()
      .then((data) => {
        if (!cancelled) setAuto(data.auto_apply === true)
      })
      .catch(() => {
        if (!cancelled) setAuto(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function startEditing() {
    setDraft(auto === true)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  async function check() {
    setChecking(true)
    try {
      await checkNow()
      await refresh()
    } catch {
      // The status line shows what the app knows; a failed request changes nothing.
    } finally {
      setChecking(false)
    }
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="New versions"
        icon={Download}
        description="Lit Review checks GitHub for new versions at startup and once a day, and downloads them in the background. Only the program’s name and version are sent, nothing about you or your work. Your data is kept when you update."
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={auto !== null && draft !== auto}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={() => commit(async () => setAuto((await saveAutoApply(draft)).auto_apply))}
      />

      {editing ? (
        <div className="flex flex-col gap-1.5">
          <Toggle label="Install new versions automatically" checked={draft} onChange={setDraft} />
          <div className="flex flex-col gap-0.5 text-xs text-gray-400">
            <p>On: you always stay up to date, with new versions applied when you start Lit Review.</p>
            <p>Off: you install updates yourself with the Install and restart button.</p>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">Installing</p>
          <p className="text-sm">
            {auto ? (
              <span className="font-medium text-[#30cf43]">Automatically. New versions get applied the next time you start Lit Review</span>
            ) : (
              <span className="text-gray-500">Manually. Updates are installed only when you approve them</span>
            )}
          </p>
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Status</p>
        <p className="text-sm text-gray-500">{describeStatus(status)}</p>
        <button
          type="button"
          onClick={check}
          disabled={checking}
          className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-60"
        >
          {checking ? 'Checking...' : 'Check now'}
        </button>
      </div>

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}
