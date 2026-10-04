import { useState } from 'react'
import { CircleDollarSign } from 'lucide-react'
import { Card } from '../ui'
import EditableCardHeader from '../EditableCardHeader'
import useSavedState from '../../lib/useSavedState'
import { DEFAULT_THRESHOLD_TEXT, formatUsd, parseThreshold, useSpendThresholdText } from '../../lib/spendSetting'

// How much a run may cost before Evaluate Papers asks first. A per-browser setting like
// PubMed's, with the same Edit/Save flow as the key cards.
export default function SpendCard() {
  const [text, setText] = useSpendThresholdText()
  const [draft, setDraft] = useState(text)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  // A damaged stored value counts as the default (as getSpendThreshold does), not as blank.
  const parsed = parseThreshold(text)
  const threshold = parsed === undefined ? parseThreshold(DEFAULT_THRESHOLD_TEXT) : parsed
  const draftValue = parseThreshold(draft)

  function startEditing() {
    setDraft(text)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="Spending"
        icon={CircleDollarSign}
        description="Evaluate Papers shows an estimated cost and asks you to confirm any run above this amount. The run stops at about the cost you confirmed. Enter 0 to confirm every run, or leave it blank for no confirmations and no limit."
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={draft.trim() !== text.trim() && draftValue !== undefined}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={() =>
          commit(async () => {
            if (draftValue === undefined) throw new Error('Enter an amount in dollars, such as 1.00, or leave it blank.')
            setText(draft.trim())
          })
        }
      />

      {editing ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor="spend-threshold" className="text-sm font-medium text-gray-700">
            Ask before spending more than (US dollars)
          </label>
          <input
            id="spend-threshold"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            inputMode="decimal"
            placeholder="No limit"
            className="w-40 rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          {draftValue === undefined ? (
            <p className="text-xs text-red-500 dark:text-red-400">Enter an amount in dollars, such as 1.00.</p>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">Ask before spending more than</p>
          <p className="text-sm text-gray-800">
            {threshold === null
              ? 'Never ask'
              : threshold === 0
                ? 'Ask before every run'
                : formatUsd(threshold)}
          </p>
        </div>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}
