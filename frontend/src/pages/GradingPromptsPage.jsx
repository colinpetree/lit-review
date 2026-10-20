import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { PageShell, Card, TextLink } from '../components/ui'
import { navIcon } from '../lib/navItems'
import MoreMenu from '../components/MoreMenu'
import ConfirmModal from '../components/ConfirmModal'
import PromptFormModal from '../components/PromptFormModal'
import { deleteJson, fetchJson, patchJson, postJson } from '../lib/api'
import { formatDateTime } from '../lib/format'
import ListFilterBar from '../components/ListFilterBar'
import InfiniteList from '../components/InfiniteList'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, sortByCreated } from '../lib/listFilter'
import { useView } from '../lib/viewSetting'
import { Cell, DataTable, ListRow, MenuCell, TruncatedText } from '../components/ListTable'
import { Tooltip } from '../components/ui/Tooltip'

const COLUMNS = [
  { label: 'Name' },
  { label: 'Criteria' },
  { label: 'Examples' },
  { label: 'Created' },
  { label: 'Updated' },
  { label: '' },
]

// Module level so React keeps one component (and the table) across renders.
const PromptsTable = (props) => <DataTable columns={COLUMNS} {...props} />

export default function GradingPromptsPage() {
  const [prompts, setPrompts] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)
  const [view, setView] = useView()
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

  const menuItems = (p) => [
    { label: 'Edit', icon: Pencil, onClick: () => setDialog({ type: 'edit', prompt: p }) },
    { label: 'Delete', icon: Trash2, danger: true, onClick: () => setDialog({ type: 'delete', prompt: p }) },
  ]

  return (
    <PageShell
      wide={view === 'table'}
      title="Grading Prompts"
      icon={navIcon('/prompts')}
      description="Reuse and refine paper grading prompts from previous evaluations to save time and get better results."
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
        New Prompt
      </button>
      {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      {prompts && prompts.length === 0 ? (
        <p className="text-sm text-gray-500">
          No prompts yet - create one here, or start a <TextLink to="/evaluations?new=1">New Evaluation</TextLink>.
        </p>
      ) : null}
      {prompts && prompts.length > 0 ? (
        <ListFilterBar
          filter={filter}
          onChange={setFilter}
          sort={sort}
          onSortChange={setSort}
          view={view}
          onViewChange={setView}
          placeholder="Filter prompts by name or criteria"
          noun="prompts"
          shown={visible.length}
          total={prompts.length}
        />
      ) : null}
      {prompts && prompts.length > 0 && visible.length === 0 ? (
        <p className="text-sm text-gray-500">No prompts match these filters.</p>
      ) : null}
      {view === 'table' ? (
        <InfiniteList
          as={PromptsTable}
          items={visible}
          resetKey={JSON.stringify([filter, sort])}
          renderItem={(p) => {
            const [name, criteria, examples, created, updated, menu] = COLUMNS
            return (
              <ListRow key={p.id} to={`/prompts/${p.id}`}>
                <Cell column={name}>
                  <Tooltip content="View details">
                    <Link to={`/prompts/${p.id}`} className="block max-w-xs truncate font-medium text-gray-800 hover:underline">
                      {p.name}
                    </Link>
                  </Tooltip>
                </Cell>
                <Cell column={criteria}>
                  <TruncatedText text={p.description} className="max-w-md text-gray-500" />
                </Cell>
                <Cell column={examples} className="text-gray-600">{p.example_count}</Cell>
                <Cell column={created} className="text-gray-600">{formatDateTime(p.created_at)}</Cell>
                <Cell column={updated} className="text-gray-600">{formatDateTime(p.updated_at)}</Cell>
                <MenuCell column={menu}>
                  <MoreMenu floating items={menuItems(p)} />
                </MenuCell>
              </ListRow>
            )
          }}
        />
      ) : (
        <InfiniteList
          as="div"
          className="flex flex-col gap-3"
          items={visible}
          resetKey={JSON.stringify([filter, sort])}
          renderItem={(p) => (
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
              <MoreMenu className="absolute right-5 top-[22px]" items={menuItems(p)} />
            </div>
          )}
        />
      )}

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
