import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import { navIcon } from '../lib/navItems'
import ListFilterBar from '../components/ListFilterBar'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, modelKey, sortByCreated } from '../lib/listFilter'
import RunMenu from '../components/RunMenu'
import { deleteJson, fetchJson } from '../lib/api'
import { datasetLabels, formatDateTime, RUN_COST_NOTE } from '../lib/format'
import ModelBadge from '../components/ModelBadge'

export default function PastResultsPage() {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)

  useEffect(() => {
    fetchJson('/api/analysis-runs')
      .then((data) => setRuns(data.runs ?? []))
      .catch((err) => setError(err.message))
  }, [])

  const visible = useMemo(
    () =>
      sortByCreated(
        filterList(runs ?? [], filter, {
          getSearchText: (r) =>
            `${r.name ?? ''} ${r.prompt_name ?? ''} ${r.grading_prompt ?? ''} ${(r.datasets ?? []).map((d) => d.name).join(' ')}`,
          getModel: (r) => (r.ai_model ? modelKey(r.ai_api, r.ai_model) : null),
        }),
        sort
      ),
    [runs, filter, sort]
  )

  const renameRun = (id, name) => setRuns((prev) => prev.map((r) => (r.id === id ? { ...r, name } : r)))

  const deleteRun = async (id) => {
    await deleteJson(`/api/analysis-runs/${id}`)
    setRuns((prev) => prev.filter((r) => r.id !== id))
  }

  return (
    <PageShell
      title="Results"
      icon={navIcon('/results')}
      description="Saved results from previous runs where the AI judge scored papers based on your research criteria."
    >
      {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      {runs && runs.length === 0 ? (
        <p className="text-sm text-gray-500">
          No evaluation runs yet - run one from Evaluate Papers.
        </p>
      ) : null}
      {runs && runs.length > 0 ? (
        <ListFilterBar
          filter={filter}
          onChange={setFilter}
          sort={sort}
          onSortChange={setSort}
          placeholder="Filter results by prompt or dataset"
          noun="results"
          shown={visible.length}
          total={runs.length}
          items={runs}
          showModelFilter
        />
      ) : null}
      {runs && runs.length > 0 && visible.length === 0 ? (
        <p className="text-sm text-gray-500">No results match these filters.</p>
      ) : null}
      <div className="flex flex-col gap-3">
        {visible.map((run) => (
          <div key={run.id} className="relative">
            <Link to={`/results/${run.id}`}>
              <Card className="hover:border-gray-300">
                <p className="pr-8 font-medium text-gray-800">{run.name || run.prompt_name || run.grading_prompt}</p>
                <p className="mt-1 text-sm text-gray-500">
                  {datasetLabels(run.datasets).join(', ')}
                  {` · ${run.paper_count} paper${run.paper_count === 1 ? '' : 's'}`}
                </p>
                <div className="mt-1 flex items-center justify-between gap-x-2 text-sm text-gray-400">
                  <div className="flex flex-wrap items-center gap-x-2">
                    <span>{formatDateTime(run.completed_at || run.created_at)} ·</span>
                    <ModelBadge aiApi={run.ai_api} aiModel={run.ai_model} cost={run.cost} costNote={RUN_COST_NOTE} />
                  </div>
                  {/* Only a run with papers still unscored gets a label; finished is the normal case. This
                      counts the papers, not the status, which can lag (excluded since) or be stale (restored). */}
                  {run.unscored_count > 0 ? (
                    <span className="shrink-0 font-medium text-amber-600 dark:text-amber-400">Incomplete</span>
                  ) : null}
                </div>
              </Card>
            </Link>
            <RunMenu
              className="absolute right-5 top-[22px]"
              run={run}
              onRenamed={(name) => renameRun(run.id, name)}
              onDelete={() => deleteRun(run.id)}
            />
          </div>
        ))}
      </div>
    </PageShell>
  )
}
