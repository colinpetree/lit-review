import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PageShell, Card, BackLink } from '../components/ui'
import PaperCard from '../components/PaperCard'
import EditableCardHeader from '../components/EditableCardHeader'
import useSavedState from '../lib/useSavedState'
import useUnsavedChangesWarning from '../lib/useUnsavedChangesWarning'
import { fetchJson, patchJson } from '../lib/api'
import { formatDateTime, formatYearRange } from '../lib/format'

// The data set's short title (editable) and the topic it was retrieved with
// (fixed), in the same preview/Edit/Save card style as the Settings page.
function DatasetDetailsCard({ dataset, onSaved }) {
  const [name, setName] = useState(dataset.name)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  const isDirty = Boolean(name.trim()) && name.trim() !== dataset.name
  useUnsavedChangesWarning(editing && isDirty)

  function startEditing() {
    setName(dataset.name)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  function save() {
    commit(async () => {
      const updated = await patchJson(`/api/datasets/${dataset.id}`, { name: name.trim() })
      onSaved(updated)
    })
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="Data set details"
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={isDirty}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={save}
      />

      <div className="flex flex-col gap-1.5">
        {editing ? (
          <>
            <label className="text-sm font-medium text-gray-700">Data set title</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={saving}
              maxLength={120}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
            />
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-gray-700">Data set title</p>
            <p className="text-sm text-gray-900">{dataset.name}</p>
          </>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Topic</p>
        <p className="whitespace-pre-wrap text-sm text-gray-900">{dataset.verbose_query}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Created</p>
        <p className="text-sm text-gray-900">{formatDateTime(dataset.created_at)}</p>
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}
    </Card>
  )
}

// A dataset is pure retrieval - never joined to any analysis run here.
// Scores only ever appear on the Analyze Papers / Past Results side; a
// paper on this page is always shown exactly as retrieved, with no score.
export default function DatasetDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [dataset, setDataset] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    setDataset(null)
    fetchJson(`/api/datasets/${id}`)
      .then((d) => !cancelled && setDataset(d))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [id])

  if (error) {
    return (
      <PageShell title="Paper Data Set">
        <p className="text-sm text-red-600">{error}</p>
      </PageShell>
    )
  }
  if (!dataset) {
    return (
      <PageShell title="Paper Data Set">
        <p className="text-sm text-gray-500">Loading…</p>
      </PageShell>
    )
  }

  const handlePaperUpdate = (updated) => {
    setDataset((prev) => ({
      ...prev,
      papers: prev.papers.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)),
    }))
  }

  const yearRange = formatYearRange(dataset.oldest_year, dataset.newest_year, dataset.newest_publication_date)

  return (
    <PageShell>
      <BackLink to="/datasets">Back to Paper Data Sets</BackLink>

      <div className="mt-4">
        <DatasetDetailsCard
          dataset={dataset}
          onSaved={(updated) => setDataset((prev) => ({ ...prev, name: updated.name }))}
        />
      </div>

      <div className="mt-6 flex items-center justify-between gap-4">
        <p className="text-sm text-gray-500">
          {dataset.papers.length} papers
          {yearRange ? ` · ${yearRange}` : ''}
          {dataset.cost ? ` · expansion cost: $${dataset.cost.toFixed(4)}` : ''}
        </p>
        <button
          type="button"
          onClick={() => navigate(`/analyze?dataset=${dataset.id}`)}
          className="shrink-0 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          Analyze Dataset
        </button>
      </div>

      <ul className="mt-4 flex flex-col gap-3">
        {dataset.papers.map((paper, index) => (
          <PaperCard
            key={paper.id ?? `${paper.doi ?? paper.title}-${index}`}
            result={paper}
            onUpdate={handlePaperUpdate}
          />
        ))}
      </ul>
    </PageShell>
  )
}
