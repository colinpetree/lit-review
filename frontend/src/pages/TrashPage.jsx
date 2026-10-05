import { useCallback, useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { PageShell, BackLink, Card } from '../components/ui'
import ConfirmModal from '../components/ConfirmModal'
import InfiniteList from '../components/InfiniteList'
import { deleteJson, fetchJson, postJson } from '../lib/api'
import { formatDateTime } from '../lib/format'
import { lastAppPath } from '../lib/lastAppPath'
import { useSettingsModal } from '../components/SettingsModalProvider'

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`

// Sections in the order "Empty trash" removes them (a run first: what it used is free once it goes).
function sections(trash) {
  return [
    {
      kind: 'run',
      title: 'Result runs',
      items: trash.runs.map((r) => ({ id: r.id, name: r.name, detail: plural(r.result_count, 'graded paper'), deletedAt: r.deleted_at })),
    },
    {
      kind: 'dataset',
      title: 'Datasets',
      items: trash.datasets.map((d) => ({
        id: d.id,
        name: d.name,
        detail: `${plural(d.paper_count, 'paper')}${d.run_count ? `, used by ${plural(d.run_count, 'result run')}` : ''}`,
        deletedAt: d.deleted_at,
      })),
    },
    {
      kind: 'prompt',
      title: 'Grading prompts',
      items: trash.prompts.map((p) => ({
        id: p.id,
        name: p.name,
        detail: `${plural(p.example_count, 'example')}${p.run_count ? `, used by ${plural(p.run_count, 'result run')}` : ''}`,
        deletedAt: p.deleted_at,
      })),
    },
  ]
}

const KIND_LABEL = { run: 'result run', dataset: 'dataset', prompt: 'prompt' }

// What was deleted but is still kept. Anything here can be restored, or removed for good
// (which cannot be undone). Reached from Settings, Your Data, not the sidebar.
export default function TrashPage() {
  const { openSettings } = useSettingsModal()
  const [trash, setTrash] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null) // { lines: [text], kept: [{ name, reason }] } | null
  const [confirm, setConfirm] = useState(null) // { kind, id, name } | 'empty' | null
  // A restore in flight: a second click on it (or another Restore) waits, or it would find
  // the item already restored and show a false error.
  const [restoring, setRestoring] = useState(false)

  const load = useCallback(() => {
    return fetchJson('/api/trash')
      .then(setTrash)
      .catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const restore = async (kind, item) => {
    if (restoring) return
    setRestoring(true)
    setError(null)
    setNotice(null)
    try {
      const result = await postJson(`/api/trash/${kind}/${item.id}/restore`, {})
      setNotice({
        lines: [
          result.name && result.name !== item.name
            ? `Restored as "${result.name}" (another run already had that name).`
            : `Restored "${item.name}".`,
        ],
        kept: [],
      })
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setRestoring(false)
    }
  }

  if (!trash) {
    return (
      <PageShell title="Deleted Items" icon={Trash2}>
        {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : <p className="text-sm text-gray-500">Loading…</p>}
      </PageShell>
    )
  }

  const groups = sections(trash)
  const total = groups.reduce((sum, g) => sum + g.items.length, 0)
  const counts = groups.filter((g) => g.items.length).map((g) => plural(g.items.length, KIND_LABEL[g.kind])).join(', ')

  return (
    <PageShell
      title="Deleted Items"
      icon={Trash2}
      description="Deleted datasets, prompts and result runs are kept here until you delete them permanently."
      actions={
        total ? (
          <button
            type="button"
            onClick={() => setConfirm('empty')}
            className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950/30"
          >
            Delete all permanently
          </button>
        ) : null
      }
    >
      <BackLink to={lastAppPath()} onClick={() => openSettings('data')}>
        Back to Your Data
      </BackLink>
      {error ? <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      {notice ? (
        <div className="mt-4 text-sm text-gray-700">
          {notice.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
          {notice.kept.length ? (
            <InfiniteList
              className="mt-3 flex flex-col gap-3 pl-5"
              items={notice.kept}
              resetKey={notice.lines.join('|')}
              renderItem={(item, i) => (
                <li key={i} className="list-disc">
                  <span className="block font-medium">{item.name}</span>
                  <span className="block text-gray-500">{item.reason}</span>
                </li>
              )}
            />
          ) : null}
        </div>
      ) : null}
      {!total ? <p className="mt-6 text-sm text-gray-500">Nothing has been deleted.</p> : null}

      <div className="mt-6 flex flex-col gap-6">
        {groups
          .filter((g) => g.items.length)
          .map((group) => (
            <section key={group.kind} className="flex flex-col gap-3">
              <div>
                <h2 className="text-lg font-semibold text-gray-800">{group.title}</h2>
                {group.note ? <p className="text-xs text-gray-400">{group.note}</p> : null}
              </div>
              <InfiniteList
                as="div"
                className="flex flex-col gap-3"
                items={group.items}
                resetKey={group.kind}
                renderItem={(item) => (
                  <Card key={item.id} className="flex items-start justify-between gap-4 !p-4">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-gray-800">{item.name}</p>
                      <p className="text-xs text-gray-500">
                        {item.detail}
                        {formatDateTime(item.deletedAt) ? ` · deleted ${formatDateTime(item.deletedAt)}` : ''}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => restore(group.kind, item)}
                        disabled={restoring}
                        className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                      >
                        Restore
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirm({ kind: group.kind, id: item.id, name: item.name })}
                        className="rounded-md px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"
                      >
                        Delete permanently
                      </button>
                    </div>
                  </Card>
                )}
              />
            </section>
          ))}
      </div>

      {confirm && confirm !== 'empty' ? (
        <ConfirmModal
          title={`Delete this ${KIND_LABEL[confirm.kind]} for good?`}
          message={`"${confirm.name}" will be removed permanently${
            confirm.kind === 'dataset' ? ', along with papers that no other dataset or example uses' : ''
          }. This cannot be undone.`}
          confirmLabel="Delete permanently"
          busyLabel="Deleting..."
          danger
          onConfirm={async () => {
            setError(null)
            setNotice(null)
            try {
              await deleteJson(`/api/trash/${confirm.kind}/${confirm.id}`)
            } finally {
              // Whatever happened, show what is there now.
              await load()
            }
          }}
          onClose={() => setConfirm(null)}
        />
      ) : null}

      {confirm === 'empty' ? (
        <ConfirmModal
          title="Permanently delete everything here?"
          message={`This permanently removes ${counts}, and the papers that nothing else uses. It cannot be undone. Anything a result run still uses is kept, and listed afterwards.`}
          confirmLabel="Delete all permanently"
          busyLabel="Deleting..."
          danger
          onConfirm={async () => {
            setError(null)
            const result = await deleteJson('/api/trash')
            const removed = result.purged.run + result.purged.dataset + result.purged.prompt
            const keptCount = result.skipped.length
            setNotice({
              // One line for what was deleted and one for what was kept, then the kept items.
              lines: [
                `Deleted ${plural(removed, 'item')}.`,
                ...(keptCount
                  ? [`Kept ${plural(keptCount, 'item')}, because a result run still uses ${keptCount === 1 ? 'it' : 'them'}:`]
                  : []),
              ],
              kept: result.skipped.map((s) => ({ name: s.name, reason: s.reason })),
            })
            await load()
          }}
          onClose={() => setConfirm(null)}
        />
      ) : null}
    </PageShell>
  )
}
