import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import DeleteMenu from '../components/DeleteMenu'
import { deleteJson } from '../lib/api'
import { datasetLabels, formatDate } from '../lib/format'

export default function PastResultsPage() {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/analysis-runs')
      .then((res) => res.json())
      .then((data) => setRuns(data.runs ?? []))
      .catch((err) => setError(err.message))
  }, [])

  const deleteRun = async (id) => {
    await deleteJson(`/api/analysis-runs/${id}`)
    setRuns((prev) => prev.filter((r) => r.id !== id))
  }

  return (
    <PageShell title="Past Results">
      {error ? <p className="text-sm text-red-600">{error}</p> : null}
      {runs && runs.length === 0 ? (
        <p className="text-sm text-gray-500">
          No analysis runs yet - run one from Discover Papers or Analyze Papers.
        </p>
      ) : null}
      <div className="flex flex-col gap-3">
        {(runs ?? []).map((run) => (
          <div key={run.id} className="relative">
            <Link to={`/results/${run.id}`}>
              <Card className="hover:border-gray-300">
                <p className="pr-8 font-medium text-gray-900">{run.grading_prompt}</p>
                <p className="mt-1 text-sm text-gray-500">{datasetLabels(run.datasets).join(', ')}</p>
                <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-sm text-gray-400">
                  <span>
                    {formatDate(run.created_at)} · {run.ai_model} · ${run.cost.toFixed(4)}
                  </span>
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
