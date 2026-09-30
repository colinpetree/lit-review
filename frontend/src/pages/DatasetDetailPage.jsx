import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PageShell } from '../components/ui'
import PaperCard from '../components/PaperCard'
import { fetchJson } from '../lib/api'
import { formatYearRange } from '../lib/format'

// A dataset is pure retrieval - never joined to any analysis run here.
// Scores only ever appear on the Analyze Papers / Past Results side; a
// paper on this page is always shown exactly as retrieved, with no score.
export default function DatasetDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [dataset, setDataset] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setError(null)
    setDataset(null)
    fetchJson(`/api/datasets/${id}`)
      .then((d) => !cancelled && setDataset(d))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [id])

  if (error) {
    return (
      <PageShell title="Paper Data Set">
        <p className="text-sm text-red-600">{error}</p>
      </PageShell>
    )
  }
  if (!dataset) {
    return (
      <PageShell title="Paper Data Set">
        <p className="text-sm text-gray-500">Loading…</p>
      </PageShell>
    )
  }

  const handlePaperUpdate = (updated) => {
    setDataset((prev) => ({
      ...prev,
      papers: prev.papers.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)),
    }))
  }

  const yearRange = formatYearRange(dataset.oldest_year, dataset.newest_year, dataset.newest_publication_date)

  return (
    <PageShell
      title={dataset.verbose_query}
      actions={
        <button
          type="button"
          onClick={() => navigate(`/analyze?dataset=${dataset.id}`)}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          Analyze Dataset
        </button>
      }
    >
      <Link to="/datasets" className="text-sm text-blue-600 hover:underline">
        ← Back to Paper Data Sets
      </Link>

      <p className="mt-4 text-sm text-gray-500">
        {dataset.papers.length} papers
        {yearRange ? ` · ${yearRange}` : ''}
        {dataset.cost ? ` · expansion cost: $${dataset.cost.toFixed(4)}` : ''}
      </p>

      <ul className="mt-4 flex flex-col gap-3">
        {dataset.papers.map((paper, index) => (
          <PaperCard
            key={paper.id ?? `${paper.doi ?? paper.title}-${index}`}
            result={paper}
            onUpdate={handlePaperUpdate}
          />
        ))}
      </ul>
    </PageShell>
  )
}
