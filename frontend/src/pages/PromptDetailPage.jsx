import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Trash2, X } from 'lucide-react'
import { PageShell, Card, BackLink } from '../components/ui'
import { ScoreBadge } from '../components/PaperCard'
import EditableCardHeader from '../components/EditableCardHeader'
import AutoGrowTextarea from '../components/AutoGrowTextarea'
import ConfirmModal from '../components/ConfirmModal'
import InfiniteList from '../components/InfiniteList'
import useSavedState from '../lib/useSavedState'
import useUnsavedChangesWarning from '../lib/useUnsavedChangesWarning'
import RunsTableList from '../components/RunsTable'
import { Tabs, TabPanel, useTab } from '../components/Tabs'
import { useJobs } from '../components/JobsProvider'
import useRuns from '../lib/useRuns'
import { deleteJson, fetchJson, patchJson } from '../lib/api'
import { formatDate } from '../lib/format'

const TABS = ['examples', 'evaluations']

const inputClass = 'w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-800'

// Name and ideal research paper contents, in the same preview/Edit/Save card style as the
// Settings page. Delete lives at the bottom while editing.
function PromptDetailsCard({ prompt, onSaved, onDelete }) {
  const [name, setName] = useState(prompt.name)
  const [description, setDescription] = useState(prompt.description)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  const isDirty =
    Boolean(name.trim()) &&
    Boolean(description.trim()) &&
    (name.trim() !== prompt.name || description.trim() !== prompt.description)

  useUnsavedChangesWarning(editing && isDirty)

  function startEditing() {
    setName(prompt.name)
    setDescription(prompt.description)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  function save() {
    commit(async () => {
      const updated = await patchJson(`/api/prompts/${prompt.id}`, {
        name: name.trim(),
        description: description.trim(),
      })
      onSaved(updated)
    })
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="Prompt details"
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={isDirty}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={save}
      />

      {editing ? (
        <>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-gray-500">Prompt title</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={saving}
              maxLength={120}
              className={inputClass}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-gray-500">Ideal research paper contents</label>
            <AutoGrowTextarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={saving}
              rows={3}
              maxLength={4000}
              className={inputClass}
            />
          </div>
          <button
            type="button"
            onClick={() => setConfirmingDelete(true)}
            disabled={saving}
            className="inline-flex items-center gap-1.5 self-end rounded-md border border-red-200 dark:border-red-900 px-3 py-1.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 disabled:opacity-50"
          >
            <Trash2 size={14} />
            Delete prompt
          </button>
        </>
      ) : (
        <>
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">Prompt title</p>
            <p className="text-sm text-gray-800">{prompt.name}</p>
          </div>
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">Ideal research paper contents</p>
            <p className="whitespace-pre-wrap text-sm text-gray-800">{prompt.description}</p>
          </div>
        </>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}

      {confirmingDelete ? (
        <ConfirmModal
          title="Delete this prompt?"
          message="This removes the prompt and its examples from your list. Past result runs that used it are not affected."
          confirmLabel="Delete"
          busyLabel="Deleting..."
          danger
          onConfirm={onDelete}
          onClose={() => setConfirmingDelete(false)}
        />
      ) : null}
    </Card>
  )
}

export default function PromptDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState(null)
  const [error, setError] = useState(null)
  const [removingExample, setRemovingExample] = useState(null)
  const [tab, setTab] = useTab(TABS)
  const { runs, setRuns, error: runsError } = useRuns()
  const [runError, setRunError] = useState(null)
  const { refreshJobs } = useJobs()
  // Newest first, as the server lists them.
  const promptRuns = useMemo(() => (runs ?? []).filter((r) => r.prompt_id === Number(id)), [runs, id])

  useEffect(() => {
    let cancelled = false
    setError(null)
    setRunError(null)
    setPrompt(null)
    fetchJson(`/api/prompts/${id}`)
      .then((p) => !cancelled && setPrompt(p))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [id])

  if (error) {
    return (
      <PageShell title="Grading Prompt">
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      </PageShell>
    )
  }
  if (!prompt) {
    return (
      <PageShell title="Grading Prompt">
        <p className="text-sm text-gray-500">Loading…</p>
      </PageShell>
    )
  }

  const deletePrompt = async () => {
    await deleteJson(`/api/prompts/${id}`)
    navigate('/prompts')
  }

  const removeExample = async (example) => {
    await deleteJson(`/api/prompts/${id}/examples/${example.id}`)
    setPrompt((prev) => ({ ...prev, examples: prev.examples.filter((e) => e.id !== example.id) }))
  }

  const renameRun = (runId, name) => setRuns((prev) => prev.map((r) => (r.id === runId ? { ...r, name } : r)))
  const deleteRun = async (runId) => {
    await deleteJson(`/api/analysis-runs/${runId}`)
    setRuns((prev) => prev.filter((r) => r.id !== runId))
    refreshJobs()
  }

  return (
    <PageShell>
      <BackLink to="/prompts">Back to Grading Prompts</BackLink>

      <div className="mt-4">
        <PromptDetailsCard
          prompt={prompt}
          onSaved={(updated) => setPrompt((prev) => ({ ...prev, ...updated }))}
          onDelete={deletePrompt}
        />
      </div>

      <Tabs
        className="mt-8"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'examples', label: 'Examples', count: prompt.examples.length },
          { id: 'evaluations', label: 'Evaluations', count: runs ? promptRuns.length : null },
        ]}
      />

      {tab === 'evaluations' ? (
        <TabPanel id="evaluations" className="mt-4">
          {runsError ? <p className="text-sm text-red-600 dark:text-red-400">{runsError}</p> : null}
          {runError ? <p className="mb-3 text-sm text-red-600 dark:text-red-400">{runError}</p> : null}
          {runs && promptRuns.length === 0 ? (
            <p className="text-sm text-gray-500">No evaluations have used this prompt yet.</p>
          ) : null}
          <RunsTableList
            compact
            runs={promptRuns}
            resetKey={prompt.id}
            onRenamed={renameRun}
            onDelete={deleteRun}
            onError={setRunError}
          />
        </TabPanel>
      ) : (
        <TabPanel id="examples" className="mt-4">
          <p className="text-sm text-gray-500">
            Add examples from a run&apos;s results with Mark as example. Only the {prompt.example_limit} most recent
            are used when grading.
          </p>
          {prompt.examples.length === 0 ? (
            <p className="mt-4 text-sm text-gray-500">No examples yet.</p>
          ) : null}
          <InfiniteList
            className="mt-4 flex flex-col gap-3"
            items={prompt.examples}
            resetKey={prompt.id}
            renderItem={(ex) => (
              <li key={ex.id} className="rounded-lg border border-gray-200 p-4">
                <div className="flex items-start justify-between gap-4">
                  <h3 className="font-medium text-gray-800">{ex.title}</h3>
                  <div className="flex shrink-0 items-center gap-2">
                    <ScoreBadge score={ex.score} />
                    <span className="text-sm text-gray-500">{ex.year ?? '—'}</span>
                    <button
                      type="button"
                      aria-label="Remove example"
                      onClick={() => setRemovingExample(ex)}
                      className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-red-600 dark:hover:text-red-400"
                    >
                      <X size={16} />
                    </button>
                  </div>
                </div>
                <p className="mt-2 text-sm italic text-gray-700">{ex.rationale}</p>
                <p className="mt-2 text-xs text-gray-400">
                  Added {formatDate(ex.created_at)}
                  {ex.source_run_id ? (
                    <>
                      {' from '}
                      <Link to={`/evaluations/${ex.source_run_id}`} className="hover:underline">
                        run #{ex.source_run_id}
                      </Link>
                    </>
                  ) : null}
                </p>
              </li>
            )}
          />
        </TabPanel>
      )}

      {removingExample ? (
        <ConfirmModal
          title="Remove this example?"
          message="Future runs of this prompt will no longer compare papers against it. Past runs are not affected."
          confirmLabel="Remove"
          busyLabel="Removing..."
          danger
          onConfirm={() => removeExample(removingExample)}
          onClose={() => setRemovingExample(null)}
        />
      ) : null}
    </PageShell>
  )
}
