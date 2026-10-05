import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import { navIcon } from '../lib/navItems'
import ListFilterBar from '../components/ListFilterBar'
import InfiniteList from '../components/InfiniteList'
import { DEFAULT_LIST_SORT, EMPTY_LIST_FILTER, filterList, modelKey, sortByCreated } from '../lib/listFilter'
import DatasetMenu from '../components/DatasetMenu'
import ModelBadge from '../components/ModelBadge'
import { deleteJson, fetchJson } from '../lib/api'
import { formatDateTime, formatYearRange } from '../lib/format'

export default function PaperDataSetsPage() {
  const [datasets, setDatasets] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_LIST_FILTER)
  const [sort, setSort] = useState(DEFAULT_LIST_SORT)

  useEffect(() => {
    fetchJson('/api/datasets')
      .then((data) => setDatasets(data.datasets ?? []))
      .catch((err) => setError(err.message))
  }, [])

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
  }

  return (
    <PageShell
      title="Paper Datasets"
      icon={navIcon('/datasets')}
      description="Groups of paper abstracts that serve as datasets for an AI model to score and rank each paper according to your research criteria."
    >
      {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
      {datasets && datasets.length === 0 ? (
        <p className="text-sm text-gray-500">
          No datasets yet - run a search from Discover Papers to create one.
        </p>
      ) : null}
      {datasets && datasets.length > 0 ? (
        <ListFilterBar
          filter={filter}
          onChange={setFilter}
          sort={sort}
          onSortChange={setSort}
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
                  <p className="mt-2 text-sm text-gray-400">
                    {d.paper_count} paper{d.paper_count === 1 ? '' : 's'}
                    {yearRange ? ` · ${yearRange}` : ''}
                  </p>
                  {formatDateTime(d.created_at) ? (
                    <p className="text-sm text-gray-400">created {formatDateTime(d.created_at)}</p>
                  ) : null}
                  {formatDateTime(d.updated_at) ? (
                    <p className="text-sm text-gray-400">updated {formatDateTime(d.updated_at)}</p>
                  ) : null}
                  <ModelBadge aiApi={d.ai_api} aiModel={d.ai_model} className="mt-1 text-sm text-gray-300" />
                </Card>
              </Link>
              <DatasetMenu
                className="absolute right-5 top-[22px]"
                dataset={d}
                onRenamed={(name) => renameDataset(d.id, name)}
                onDelete={() => deleteDataset(d.id)}
              />
            </div>
          )
        }}
      />
    </PageShell>
  )
}
