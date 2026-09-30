import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PageShell } from '../components/ui'
import PaperCard from '../components/PaperCard'
import { fetchJson } from '../lib/api'
import { driveAnalysisRun, mergeRunResults } from '../lib/driveAnalysisRun'

export default function RunResultsPage() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [error, setError] = useState(null)
  const [resuming, setResuming] = useState(false)
  // /results/:id is one long-lived route element - React Router doesn't
  // remount it on a param-only change, so a "Resume scoring" loop started
  // on one run keeps running (and keeps calling setRun) even after the
  // user navigates to a different run's id. Aborting the leftover request
  // when id changes stops both the stale network calls and the stale
  // setRun calls that would otherwise overwrite the newly-loaded run.
  const activeRequestRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    activeRequestRef.current?.abort()
    setError(null)
    setRun(null)
    setResuming(false)
    fetchJson(`/api/analysis-runs/${id}`)
      .then((r) => !cancelled && setRun(mergeRunResults(r)))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [id])

  const resumeScoring = async () => {
    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setResuming(true)
    setError(null)
    try {
      await driveAnalysisRun(id, controller.signal, (updated) => {
        if (!controller.signal.aborted) setRun(updated)
      })
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally {
      if (!controller.signal.aborted) setResuming(false)
    }
  }

  if (error) {
    return (
      <PageShell title="Run Results">
        <p className="text-sm text-red-600">{error}</p>
      </PageShell>
    )
  }
  if (!run) {
    return (
      <PageShell title="Run Results">
        <p className="text-sm text-gray-500">Loading…</p>
      </PageShell>
    )
  }

  const handlePaperUpdate = (updated) => {
    setRun((prev) => ({
      ...prev,
      results: prev.results.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)),
    }))
  }

  return (
    <PageShell title={run.grading_prompt}>
      <Link to="/results" className="text-sm text-blue-600 hover:underline">
        ← Back to Past Results
      </Link>

      <p className="mt-4 text-sm text-gray-500">
        Datasets: {run.datasets.map((d) => d.verbose_query).join(', ')}
      </p>
      <p className="mt-1 text-sm text-gray-500">
        {run.ai_model} · {run.status} · ${run.cost.toFixed(4)}
      </p>

      {run.remaining > 0 ? (
        <button
          type="button"
          onClick={resumeScoring}
          disabled={resuming}
          className="mt-3 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
        >
          {resuming ? `Scoring… ${run.remaining} remaining` : `Resume scoring (${run.remaining} unscored)`}
        </button>
      ) : null}

      <ul className="mt-4 flex flex-col gap-3">
        {run.results.map((paper, index) => (
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
