import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'

export default function PastResultsPage() {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/analysis-runs')
      .then((res) => res.json())
      .then((data) => setRuns(data.runs ?? []))
      .catch((err) => setError(err.message))
  }, [])

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
          <Link key={run.id} to={`/results/${run.id}`}>
            <Card className="hover:border-gray-300">
              <div className="flex items-start justify-between gap-4">
                <p className="font-medium text-gray-900">{run.grading_prompt}</p>
                <span className="shrink-0 text-xs uppercase text-gray-400">{run.status}</span>
              </div>
              <p className="mt-1 text-sm text-gray-500">{run.dataset_names}</p>
              <p className="mt-1 text-sm text-gray-400">
                {run.ai_model} · ${run.cost.toFixed(4)}
              </p>
            </Card>
          </Link>
        ))}
      </div>
    </PageShell>
  )
}
