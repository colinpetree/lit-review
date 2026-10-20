import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageShell, Card } from '../components/ui'
import NewEvaluationModal from '../components/NewEvaluationModal'
import JobStatus from '../components/JobStatus'
import { useJobs } from '../components/JobsProvider'
import { navIcon } from '../lib/navItems'
import ListFilterBar from '../components/ListFilterBar'
import InfiniteList from '../components/InfiniteList'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, modelKey, sortByCreated } from '../lib/listFilter'
import RunMenu from '../components/RunMenu'
import RunsTableList from '../components/RunsTable'
import { deleteJson } from '../lib/api'
import { datasetLabels, formatDateTime, RUN_COST_NOTE } from '../lib/format'
import ModelBadge from '../components/ModelBadge'
import { useView } from '../lib/viewSetting'
import useRuns from '../lib/useRuns'

export default function PaperEvaluationsPage() {
  const { runs, setRuns, error } = useRuns()
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)
  const [view, setView] = useView()
  // The dataset ids a New Evaluation starts with selected; null while the dialog is closed.
  const [creating, setCreating] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const { refreshJobs } = useJobs()

  // /evaluations?new=1&dataset=<id> (from a dataset page or the prompts page) opens the New
  // Evaluation dialog, then drops the parameters.
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      const id = Number(searchParams.get('dataset'))
      setCreating(Number.isInteger(id) && id > 0 ? [id] : [])
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

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
    refreshJobs()
  }

  return (
    <PageShell
      wide={view === 'table'}
      title="Paper Evaluations"
      icon={navIcon('/evaluations')}
      description="Saved evaluations of research papers graded by an AI judge based on your research criteria and sorted by most relevant."
    >
      <button
        type="button"
        onClick={() => setCreating([])}
        className="mb-6 inline-flex items-center gap-1.5 rounded-md border border-blue-600 bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:border-blue-700 hover:bg-blue-700"
      >
        <Plus size={16} />
        New Evaluation
      </button>
      {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      {actionError ? <p className="mb-3 text-sm text-red-600 dark:text-red-400">{actionError}</p> : null}
      {runs && runs.length === 0 ? (
        <p className="text-sm text-gray-500">
          No evaluations yet. Click <span className="font-medium">+ New Evaluation</span> to grade a dataset against your research criteria.
        </p>
      ) : null}
      {runs && runs.length > 0 ? (
        <ListFilterBar
          filter={filter}
          onChange={setFilter}
          sort={sort}
          onSortChange={setSort}
          view={view}
          onViewChange={setView}
          placeholder="Filter evaluations by prompt or dataset"
          noun="evaluations"
          shown={visible.length}
          total={runs.length}
          items={runs}
          showModelFilter
        />
      ) : null}
      {runs && runs.length > 0 && visible.length === 0 ? (
        <p className="text-sm text-gray-500">No evaluations match these filters.</p>
      ) : null}
      {view === 'table' ? (
        <RunsTableList
          runs={visible}
          resetKey={JSON.stringify([filter, sort])}
          onRenamed={renameRun}
          onDelete={deleteRun}
          onError={setActionError}
        />
      ) : (
      <InfiniteList
        as="div"
        className="flex flex-col gap-3"
        items={visible}
        resetKey={JSON.stringify([filter, sort])}
        renderItem={(run) => (
          <div key={run.id} className="relative">
            <Link to={`/evaluations/${run.id}`}>
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
                  {/* The server works the state out (a run with papers still ungraded and nothing grading
                      them is Incomplete, whatever its status says). */}
                  <JobStatus item={run} showProgress={false} hideCompleted />
                </div>
              </Card>
            </Link>
            <RunMenu
              className="absolute right-5 top-[22px]"
              run={run}
              onRenamed={(name) => renameRun(run.id, name)}
              onDelete={() => deleteRun(run.id)}
              onError={setActionError}
            />
          </div>
        )}
      />
      )}
      {creating ? <NewEvaluationModal initialDatasetIds={creating} onClose={() => setCreating(null)} /> : null}
    </PageShell>
  )
}
