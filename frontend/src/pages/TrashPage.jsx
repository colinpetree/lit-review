import { useCallback, useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { PageShell, BackLink, Card } from '../components/ui'
import InfiniteList from '../components/InfiniteList'
import { fetchJson, postJson } from '../lib/api'
import { formatDateTime } from '../lib/format'
import { lastAppPath } from '../lib/lastAppPath'
import { useSettingsModal } from '../components/SettingsModalProvider'

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`

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

// What was deleted but is still kept. Deleting is always a soft delete: anything here can be
// restored, and nothing here is removed for good. Reached from Settings, Your Data, not the sidebar.
export default function TrashPage() {
  const { openSettings } = useSettingsModal()
  const [trash, setTrash] = useState(null)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
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
      setNotice(
        result.name && result.name !== item.name
          ? `Restored as "${result.name}" (another run already had that name).`
          : `Restored "${item.name}".`,
      )
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

  return (
    <PageShell
      title="Deleted Items"
      icon={Trash2}
      description="Deleted datasets, prompts and result runs are kept here. Restore anything to bring it back."
    >
      <BackLink to={lastAppPath()} onClick={() => openSettings('data')}>
        Back to Your Data
      </BackLink>
      {error ? <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      {notice ? <p className="mt-4 text-sm text-gray-700">{notice}</p> : null}
      {!total ? <p className="mt-6 text-sm text-gray-500">Nothing has been deleted.</p> : null}

      <div className="mt-6 flex flex-col gap-6">
        {groups
          .filter((g) => g.items.length)
          .map((group) => (
            <section key={group.kind} className="flex flex-col gap-3">
              <h2 className="text-lg font-semibold text-gray-800">{group.title}</h2>
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
                    <button
                      type="button"
                      onClick={() => restore(group.kind, item)}
                      disabled={restoring}
                      className="shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                    >
                      Restore
                    </button>
                  </Card>
                )}
              />
            </section>
          ))}
      </div>
    </PageShell>
  )
}
