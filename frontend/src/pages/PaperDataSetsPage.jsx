import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { PageShell, Card } from '../components/ui'
import NewDatasetModal from '../components/NewDatasetModal'
import JobStatus, { JobStatusDot } from '../components/JobStatus'
import { useJobs } from '../components/JobsProvider'
import { navIcon } from '../lib/navItems'
import ListFilterBar from '../components/ListFilterBar'
import InfiniteList from '../components/InfiniteList'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, modelKey, sortByCreated } from '../lib/listFilter'
import DatasetMenu from '../components/DatasetMenu'
import ModelBadge from '../components/ModelBadge'
import { deleteJson, fetchJson } from '../lib/api'
import { formatDateTime, formatYearRange } from '../lib/format'
import { useView } from '../lib/viewSetting'
import { Cell, DataTable, ListRow, MenuCell, TruncatedText } from '../components/ListTable'
import { Tooltip } from '../components/ui/Tooltip'

const COLUMNS = [
  { label: 'Name' },
  { label: 'Topic' },
  { label: 'Papers' },
  { label: 'Years' },
  { label: 'Created' },
  { label: 'Updated' },
  { label: 'AI model' },
  { label: '' },
]

// Module level so React keeps one component (and the table) across renders.
const DatasetsTable = (props) => <DataTable columns={COLUMNS} {...props} />

export default function PaperDataSetsPage() {
  const [datasets, setDatasets] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)
  const [view, setView] = useView()
  const [creating, setCreating] = useState(false)
  const [actionError, setActionError] = useState(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const { statusKey, refreshJobs } = useJobs()

  // /datasets?new=1 (from another page) opens the New Dataset dialog, then drops the parameter.
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setCreating(true)
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // Loaded again whenever a job starts, stops or ends, so each card's status stays true. A
  // failed reload keeps the list that is showing; only the first load reports an error.
  const loaded = useRef(false)
  useEffect(() => {
    let cancelled = false
    fetchJson('/api/datasets')
      .then((data) => {
        if (cancelled) return
        loaded.current = true
        setDatasets(data.datasets ?? [])
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
        filterList(datasets ?? [], filter, {
          getSearchText: (d) => `${d.name ?? ''} ${d.verbose_query ?? ''}`,
          getModel: (d) => (d.ai_model ? modelKey(d.ai_api, d.ai_model) : null),
        }),
        sort
      ),
    [datasets, filter, sort]
  )

  const renameDataset = (id, name) => setDatasets((prev) => prev.map((d) => (d.id === id ? { ...d, name } : d)))

  const deleteDataset = async (id) => {
    await deleteJson(`/api/datasets/${id}`)
    setDatasets((prev) => prev.filter((d) => d.id !== id))
    refreshJobs()
  }

  return (
    <PageShell
      wide={view === 'table'}
      title="Paper Datasets"
      icon={navIcon('/datasets')}
      description="Groups of similar research papers that contain paper data including title, abstract, authors, publication, and number of citations. Datasets are used in evaluations."
    >
      <button
        type="button"
        onClick={() => setCreating(true)}
        className="mb-6 inline-flex items-center gap-1.5 rounded-md border border-blue-600 bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:border-blue-700 hover:bg-blue-700"
      >
        <Plus size={16} />
        New Dataset
      </button>
      {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      {actionError ? <p className="mb-3 text-sm text-red-600 dark:text-red-400">{actionError}</p> : null}
      {datasets && datasets.length === 0 ? (
        <p className="text-sm text-gray-500">
          No datasets yet. Click <span className="font-medium">+ New Dataset</span> to search for papers on a topic.
        </p>
      ) : null}
      {datasets && datasets.length > 0 ? (
        <ListFilterBar
          filter={filter}
          onChange={setFilter}
          sort={sort}
          onSortChange={setSort}
          view={view}
          onViewChange={setView}
          placeholder="Filter datasets by title or topic"
          noun="datasets"
          shown={visible.length}
          total={datasets.length}
          items={datasets}
          showModelFilter
        />
      ) : null}
      {datasets && datasets.length > 0 && visible.length === 0 ? (
        <p className="text-sm text-gray-500">No datasets match these filters.</p>
      ) : null}
      {view === 'table' ? (
        <InfiniteList
          as={DatasetsTable}
          items={visible}
          resetKey={JSON.stringify([filter, sort])}
          renderItem={(d) => {
            const [name, query, papers, years, created, updated, model, menu] = COLUMNS
            const yearRange = formatYearRange(d.oldest_year, d.newest_year, d.newest_publication_date)
            return (
              <ListRow key={d.id} to={`/datasets/${d.id}`}>
                <Cell column={name}>
                  <div className="flex items-center gap-2">
                    <JobStatusDot item={d} />
                    <Tooltip content="View details">
                      <Link to={`/datasets/${d.id}`} className="block max-w-xs truncate font-medium text-gray-800 hover:underline">
                        {d.name}
                      </Link>
                    </Tooltip>
                  </div>
                </Cell>
                <Cell column={query}>
                  <TruncatedText text={d.verbose_query} className="max-w-md text-gray-500" />
                </Cell>
                <Cell column={papers} className="text-gray-600">{d.pending ? '' : d.paper_count}</Cell>
                <Cell column={years} className="text-gray-600">{d.pending ? '' : yearRange}</Cell>
                <Cell column={created} className="text-gray-600">{formatDateTime(d.created_at)}</Cell>
                <Cell column={updated} className="text-gray-600">{formatDateTime(d.updated_at)}</Cell>
                <Cell column={model}>
                  <ModelBadge aiApi={d.ai_api} aiModel={d.ai_model} className="text-sm text-gray-600" />
                </Cell>
                <MenuCell column={menu}>
                  <DatasetMenu
                    floating
                    dataset={d}
                    onRenamed={(n) => renameDataset(d.id, n)}
                    onDelete={() => deleteDataset(d.id)}
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
        className="grid grid-cols-1 sm:grid-cols-2 gap-4"
        items={visible}
        resetKey={JSON.stringify([filter, sort])}
        renderItem={(d) => {
          const yearRange = formatYearRange(d.oldest_year, d.newest_year, d.newest_publication_date)
          return (
            <div key={d.id} className="relative">
              <Link to={`/datasets/${d.id}`}>
                <Card className="h-full hover:border-gray-300">
                  <p className="font-medium text-gray-800 pr-8">{d.name}</p>
                  <p className="mt-1 line-clamp-2 text-sm text-gray-500">{d.verbose_query}</p>
                  {d.pending ? null : (
                    <p className="mt-2 text-sm text-gray-400">
                      {d.paper_count} paper{d.paper_count === 1 ? '' : 's'}
                      {yearRange ? ` · ${yearRange}` : ''}
                    </p>
                  )}
                  {formatDateTime(d.created_at) ? (
                    <p className="text-sm text-gray-400">created {formatDateTime(d.created_at)}</p>
                  ) : null}
                  {formatDateTime(d.updated_at) ? (
                    <p className="text-sm text-gray-400">updated {formatDateTime(d.updated_at)}</p>
                  ) : null}
                  <div className="mt-1 flex items-center justify-between gap-2">
                    <ModelBadge aiApi={d.ai_api} aiModel={d.ai_model} className="text-sm text-gray-300" />
                    <JobStatus item={d} showProgress={false} hideCompleted />
                  </div>
                </Card>
              </Link>
              <DatasetMenu
                className="absolute right-5 top-[22px]"
                dataset={d}
                onRenamed={(name) => renameDataset(d.id, name)}
                onDelete={() => deleteDataset(d.id)}
                onError={setActionError}
              />
            </div>
          )
        }}
      />
      )}
      {creating ? <NewDatasetModal onClose={() => setCreating(false)} /> : null}
    </PageShell>
  )
}
