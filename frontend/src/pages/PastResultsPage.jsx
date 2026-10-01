import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import ListFilterBar from '../components/ListFilterBar'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, modelKey, sortByCreated } from '../lib/listFilter'
import DeleteMenu from '../components/DeleteMenu'
import { deleteJson } from '../lib/api'
import { datasetLabels, formatDateTime } from '../lib/format'
import ModelBadge from '../components/ModelBadge'

export default function PastResultsPage() {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)

  useEffect(() => {
    fetch('/api/analysis-runs')
      .then((res) => res.json())
      .then((data) => setRuns(data.runs ?? []))
      .catch((err) => setError(err.message))
  }, [])

  const visible = useMemo(
    () =>
      sortByCreated(
        filterList(runs ?? [], filter, {
          getSearchText: (r) =>
            `${r.prompt_name ?? ''} ${r.grading_prompt ?? ''} ${(r.datasets ?? []).map((d) => d.name).join(' ')}`,
          getModel: (r) => (r.ai_model ? modelKey(r.ai_api, r.ai_model) : null),
        }),
        sort
      ),
    [runs, filter, sort]
  )

  const deleteRun = async (id) => {
    await deleteJson(`/api/analysis-runs/${id}`)
    setRuns((prev) => prev.filter((r) => r.id !== id))
  }

  return (
    <PageShell
      title="Analysis Results"
      description="Saved results from previous runs where the AI judge scored papers based on your research criteria."
    >
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      {runs && runs.length === 0 ? (
        <p className="text-sm text-gray-500">
          No analysis runs yet - run one from Discover Papers or Analyze Papers.
        </p>
      ) : null}
      {runs && runs.length > 0 ? (
        <ListFilterBar
          filter={filter}
          onChange={setFilter}
          sort={sort}
          onSortChange={setSort}
          placeholder="Filter results by prompt or data set"
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
                <p className="pr-8 font-medium text-gray-900">{run.prompt_name || run.grading_prompt}</p>
                <p className="mt-1 text-sm text-gray-500">
                  {datasetLabels(run.datasets).join(', ')}
                  {` · ${run.paper_count} paper${run.paper_count === 1 ? '' : 's'}`}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-gray-400">
                  <span>{formatDateTime(run.completed_at || run.created_at)} ·</span>
                  <ModelBadge aiApi={run.ai_api} aiModel={run.ai_model} cost={run.cost} />
                  <span className="ml-auto text-xs uppercase">{run.status}</span>
                </div>
              </Card>
            </Link>
            <DeleteMenu
              className="absolute right-5 top-[22px]"
              title="Delete this result run?"
              message="This removes the run and its scores from your results. The papers and datasets are not affected."
              onConfirm={() => deleteRun(run.id)}
            />
          </div>
        ))}
      </div>
    </PageShell>
  )
}
