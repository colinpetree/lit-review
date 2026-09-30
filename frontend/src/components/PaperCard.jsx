import { useState } from 'react'
import { BookmarkPlus, Pencil } from 'lucide-react'
import { patchJson } from '../lib/api'
import MoreMenu from './MoreMenu'
import ConfirmModal from './ConfirmModal'
import AutoGrowTextarea from './AutoGrowTextarea'

export function ScoreBadge({ score }) {
  if (score === null || score === undefined) return null
  const color =
    score >= 65 ? 'bg-green-100 text-green-800' : score >= 40 ? 'bg-yellow-100 text-yellow-800' : 'bg-gray-100 text-gray-600'
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {score}/100
    </span>
  )
}

function EditForm({ result, onSave, onCancel }) {
  const [form, setForm] = useState({
    title: result.title || '',
    abstract: result.abstract || '',
    doi: result.doi || '',
    venue: result.venue || '',
    year: result.year ?? '',
    url: result.url || '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const save = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const updated = await patchJson(`/api/papers/${result.id}`, {
        title: form.title,
        abstract: form.abstract,
        doi: form.doi,
        venue: form.venue,
        year: form.year === '' ? null : Number(form.year),
        url: form.url,
      })
      onSave(updated)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  const field = 'rounded-md border border-gray-300 px-2 py-1.5 text-sm w-full'
  const label = 'text-xs font-medium text-gray-500'

  return (
    <li className="border border-gray-200 rounded-lg p-4">
      <form onSubmit={save} className="flex flex-col gap-3">
        <div>
          <label className={label}>Title</label>
          <input value={form.title} onChange={set('title')} className={field} />
        </div>
        <div>
          <label className={label}>Abstract</label>
          <AutoGrowTextarea value={form.abstract} onChange={set('abstract')} rows={4} className={field} />
        </div>
        <div className="flex gap-3">
          <div className="flex-1">
            <label className={label}>DOI</label>
            <input value={form.doi} onChange={set('doi')} className={field} />
          </div>
          <div className="w-24">
            <label className={label}>Year</label>
            <input type="number" value={form.year} onChange={set('year')} className={field} />
          </div>
        </div>
        <div>
          <label className={label}>Venue</label>
          <input value={form.venue} onChange={set('venue')} className={field} />
        </div>
        <div>
          <label className={label}>URL</label>
          <input value={form.url} onChange={set('url')} className={field} />
        </div>

        {error ? <p className="text-xs text-red-600">{error}</p> : null}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={saving || !form.title.trim()}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
          >
            Cancel
          </button>
        </div>
      </form>
    </li>
  )
}

// onUpdate enables the Edit action. onMarkExample (run results only) enables
// "Mark as example" for a scored paper that isn't already one.
export default function PaperCard({ result, onUpdate, onMarkExample }) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [markingExample, setMarkingExample] = useState(false)

  const menuItems = []
  if (onUpdate) menuItems.push({ label: 'Edit', icon: Pencil, onClick: () => setEditing(true) })
  if (onMarkExample && result.score != null && !result.is_example) {
    menuItems.push({ label: 'Mark as example', icon: BookmarkPlus, onClick: () => setMarkingExample(true) })
  }

  if (editing) {
    return (
      <EditForm
        result={result}
        onCancel={() => setEditing(false)}
        onSave={(updated) => {
          onUpdate?.(updated)
          setEditing(false)
        }}
      />
    )
  }

  return (
    <li className="border border-gray-200 rounded-lg p-4 hover:border-gray-300">
      <div className="flex items-start justify-between gap-4">
        <h3 className="font-medium text-gray-900">
          {result.url ? (
            <a
              href={result.url}
              target="_blank"
              rel="noreferrer"
              className="hover:underline"
            >
              {result.title}
            </a>
          ) : (
            result.title
          )}
        </h3>
        <div className="flex shrink-0 items-center gap-2">
          {result.is_example ? (
            <span className="shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
              Example
            </span>
          ) : null}
          <ScoreBadge score={result.score} />
          <span className="text-sm text-gray-500">{result.year ?? '—'}</span>
          {menuItems.length ? <MoreMenu items={menuItems} /> : null}
        </div>
      </div>

      <p className="mt-1 text-sm text-gray-500">
        {(() => {
          const named = result.authors.filter(Boolean)
          return (
            <>
              {named.slice(0, 5).join(', ')}
              {named.length > 5 ? ', et al.' : ''}
            </>
          )
        })()}
        {result.venue ? ` · ${result.venue}` : ''}
        {' · '}
        {result.citation_count} citation{result.citation_count === 1 ? '' : 's'}
        {result.is_review ? ' · review' : ''}
      </p>

      {result.rationale ? (
        <p className="mt-2 text-sm text-gray-700 italic">{result.rationale}</p>
      ) : null}

      {result.abstract ? (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-sm text-blue-600 hover:underline"
          >
            {expanded ? 'Hide abstract' : 'Show abstract'}
          </button>
          {expanded ? (
            <p className="mt-2 text-sm text-gray-700">{result.abstract}</p>
          ) : null}
        </div>
      ) : (
        <p className="mt-2 text-sm text-gray-400 italic">No abstract available</p>
      )}

      {markingExample ? (
        <ConfirmModal
          title="Mark as example?"
          message="This paper's score and reasoning will be added as a good example for this run's prompt. Future runs of the prompt will compare papers against it."
          confirmLabel="Mark as example"
          busyLabel="Saving..."
          onConfirm={() => onMarkExample(result)}
          onClose={() => setMarkingExample(false)}
        />
      ) : null}
    </li>
  )
}
