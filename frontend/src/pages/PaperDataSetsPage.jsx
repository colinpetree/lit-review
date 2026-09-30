import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import DeleteMenu from '../components/DeleteMenu'
import { deleteJson } from '../lib/api'
import { formatYearRange } from '../lib/format'

export default function PaperDataSetsPage() {
  const [datasets, setDatasets] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/datasets')
      .then((res) => res.json())
      .then((data) => setDatasets(data.datasets ?? []))
      .catch((err) => setError(err.message))
  }, [])

  const deleteDataset = async (id) => {
    await deleteJson(`/api/datasets/${id}`)
    setDatasets((prev) => prev.filter((d) => d.id !== id))
  }

  return (
    <PageShell title="Paper Data Sets">
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      {datasets && datasets.length === 0 ? (
        <p className="text-sm text-gray-500">
          No datasets yet - run a search from Discover Papers to create one.
        </p>
      ) : null}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {(datasets ?? []).map((d) => {
          const yearRange = formatYearRange(d.oldest_year, d.newest_year, d.newest_publication_date)
          return (
            <div key={d.id} className="relative">
              <Link to={`/datasets/${d.id}`}>
                <Card className="h-full hover:border-gray-300">
                  <p className="font-medium text-gray-900 pr-8">{d.verbose_query}</p>
                  <p className="mt-2 text-sm text-gray-500">
                    {d.paper_count} paper{d.paper_count === 1 ? '' : 's'}
                    {yearRange ? ` · ${yearRange}` : ''}
                  </p>
                </Card>
              </Link>
              <DeleteMenu
                className="absolute right-5 top-[22px]"
                title="Delete this data set?"
                message="This removes the data set from your list. Past result runs that used it and the papers themselves are not deleted."
                onConfirm={() => deleteDataset(d.id)}
              />
            </div>
          )
        })}
      </div>
    </PageShell>
  )
}
