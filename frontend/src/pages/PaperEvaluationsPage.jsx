import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageShell, Card } from '../components/ui'
import NewEvaluationModal from '../components/NewEvaluationModal'
import JobStatus, { JobStatusDot } from '../components/JobStatus'
import { useJobs } from '../components/JobsProvider'
import { navIcon } from '../lib/navItems'
import ListFilterBar from '../components/ListFilterBar'
import InfiniteList from '../components/InfiniteList'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, modelKey, sortByCreated } from '../lib/listFilter'
import RunMenu from '../components/RunMenu'
import { deleteJson, fetchJson } from '../lib/api'
import { datasetLabels, formatDateTime, RUN_COST_NOTE } from '../lib/format'
import ModelBadge from '../components/ModelBadge'
import { useView } from '../lib/viewSetting'
import { Cell, DataTable, ListRow, MenuCell, TruncatedText } from '../components/ListTable'
import { Tooltip } from '../components/ui/Tooltip'

const COLUMNS = [
  { label: 'Name' },
  { label: 'Datasets' },
  { label: 'Papers' },
  { label: 'Date' },
  { label: 'AI model' },
  { label: 'Est. cost' },
  { label: '' },
]

// Module level so React keeps one component (and the table) across renders.
const RunsTable = (props) => <DataTable columns={COLUMNS} {...props} />

export default function PaperEvaluationsPage() {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)
  const [view, setView] = useView()
  // The dataset ids a New Evaluation starts with selected; null while the dialog is closed.
  const [creating, setCreating] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const { statusKey, refreshJobs } = useJobs()

  // /evaluations?new=1&dataset=<id> (from a dataset page or the prompts page) opens the New
  // Evaluation dialog, then drops the parameters.
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      const id = Number(searchParams.get('dataset'))
      setCreating(Number.isInteger(id) && id > 0 ? [id] : [])
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // Loaded again whenever a job starts, stops or ends, so each card's status stays true. A
  // failed reload keeps the list that is showing; only the first load reports an error.
  const loaded = useRef(false)
  useEffect(() => {
    let cancelled = false
    fetchJson('/api/analysis-runs')
      .then((data) => {
        if (cancelled) return
        loaded.current = true
        setRuns(data.runs ?? [])
        setError(null)
      })
      .catch((err) => {
        if (!cancelled && !loaded.current) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [statusKey])

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
        <InfiniteList
          as={RunsTable}
          items={visible}
          resetKey={JSON.stringify([filter, sort])}
          renderItem={(run) => {
            const [name, datasets, papers, date, model, cost, menu] = COLUMNS
            const title = run.name || run.prompt_name || run.grading_prompt
            const datasetText = datasetLabels(run.datasets).join(', ')
            return (
              <ListRow key={run.id} to={`/evaluations/${run.id}`}>
                <Cell column={name}>
                  <div className="flex items-center gap-2">
                    <JobStatusDot item={run} />
                    <Tooltip content="View details">
                      <Link to={`/evaluations/${run.id}`} className="block max-w-xs truncate font-medium text-gray-800 hover:underline">
                        {title}
                      </Link>
                    </Tooltip>
                  </div>
                </Cell>
                <Cell column={datasets}>
                  <TruncatedText text={datasetText} className="max-w-md text-gray-500" />
                </Cell>
                <Cell column={papers} className="text-gray-600">{run.paper_count}</Cell>
                <Cell column={date} className="text-gray-600">{formatDateTime(run.completed_at || run.created_at)}</Cell>
                <Cell column={model}>
                  <ModelBadge aiApi={run.ai_api} aiModel={run.ai_model} className="text-sm text-gray-600" />
                </Cell>
                <Cell column={cost} className="text-gray-600">
                  {run.cost != null ? <span title={RUN_COST_NOTE}>${run.cost.toFixed(2)}</span> : null}
                </Cell>
                <MenuCell column={menu}>
                  <RunMenu
                    floating
                    run={run}
                    onRenamed={(n) => renameRun(run.id, n)}
                    onDelete={() => deleteRun(run.id)}
                    onError={setActionError}
                  />
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
