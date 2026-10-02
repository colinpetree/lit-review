import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { PageShell, Card } from '../components/ui'
import { navIcon } from '../lib/navItems'
import MoreMenu from '../components/MoreMenu'
import ConfirmModal from '../components/ConfirmModal'
import PromptFormModal from '../components/PromptFormModal'
import { deleteJson, fetchJson, patchJson, postJson } from '../lib/api'
import { formatDateTime } from '../lib/format'
import ListFilterBar from '../components/ListFilterBar'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, sortByCreated } from '../lib/listFilter'

export default function ScoringPromptsPage() {
  const [prompts, setPrompts] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)
  // null | { type: 'create' } | { type: 'edit' | 'delete', prompt }
  const [dialog, setDialog] = useState(null)

  useEffect(() => {
    fetchJson('/api/prompts')
      .then((data) => setPrompts(data.prompts ?? []))
      .catch((err) => setError(err.message))
  }, [])

  const visible = useMemo(
    () =>
      sortByCreated(
        filterList(prompts ?? [], filter, {
          getSearchText: (p) => `${p.name ?? ''} ${p.description ?? ''}`,
        }),
        sort
      ),
    [prompts, filter, sort]
  )

  const createPrompt = async (fields) => {
    const created = await postJson('/api/prompts', fields)
    setPrompts((prev) => [{ ...created, example_count: 0 }, ...(prev ?? [])])
  }

  const editPrompt = async (id, fields) => {
    const updated = await patchJson(`/api/prompts/${id}`, fields)
    setPrompts((prev) =>
      prev.map((p) => (p.id === id ? { ...p, ...fields, updated_at: updated.updated_at } : p))
    )
  }

  const deletePrompt = async (id) => {
    await deleteJson(`/api/prompts/${id}`)
    setPrompts((prev) => prev.filter((p) => p.id !== id))
  }

  return (
    <PageShell
      title="Scoring Prompts"
      icon={navIcon('/prompts')}
      description="Refine and re-use paper scoring prompts from previous runs to get better results."
    >
      <button
        type="button"
        onClick={() => setDialog({ type: 'create' })}
        // Wait for the list to load (or fail) so a new prompt can't be lost to
        // the initial fetch replacing the list.
        disabled={prompts === null && !error}
        className="mb-6 inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        <Plus size={16} />
        New prompt
      </button>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      {prompts && prompts.length === 0 ? (
        <p className="text-sm text-gray-500">
          No prompts yet - create one here, or run an analysis from Analyze Papers.
        </p>
      ) : null}
      {prompts && prompts.length > 0 ? (
        <ListFilterBar
          filter={filter}
          onChange={setFilter}
          sort={sort}
          onSortChange={setSort}
          placeholder="Filter prompts by name or criteria"
          noun="prompts"
          shown={visible.length}
          total={prompts.length}
        />
      ) : null}
      {prompts && prompts.length > 0 && visible.length === 0 ? (
        <p className="text-sm text-gray-500">No prompts match these filters.</p>
      ) : null}
      <div className="flex flex-col gap-3">
        {visible.map((p) => (
          <div key={p.id} className="relative">
            <Link to={`/prompts/${p.id}`}>
              <Card className="hover:border-gray-300">
                <p className="pr-8 font-medium text-gray-800">{p.name}</p>
                <p className="mt-1 line-clamp-2 text-sm text-gray-500">{p.description}</p>
                <p className="mt-1 text-sm text-gray-400">
                  {p.example_count} example{p.example_count === 1 ? '' : 's'} · {formatDateTime(p.created_at)}
                </p>
              </Card>
            </Link>
            <MoreMenu
              className="absolute right-5 top-[22px]"
              items={[
                { label: 'Edit', icon: Pencil, onClick: () => setDialog({ type: 'edit', prompt: p }) },
                { label: 'Delete', icon: Trash2, danger: true, onClick: () => setDialog({ type: 'delete', prompt: p }) },
              ]}
            />
          </div>
        ))}
      </div>

      {dialog?.type === 'create' ? (
        <PromptFormModal heading="New prompt" onSave={createPrompt} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.type === 'edit' ? (
        <PromptFormModal
          heading="Edit prompt"
          initial={dialog.prompt}
          onSave={(fields) => editPrompt(dialog.prompt.id, fields)}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.type === 'delete' ? (
        <ConfirmModal
          title="Delete this prompt?"
          message="This removes the prompt and its examples from your list. Past result runs that used it are not affected."
          confirmLabel="Delete"
          busyLabel="Deleting..."
          danger
          onConfirm={() => deletePrompt(dialog.prompt.id)}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </PageShell>
  )
}
