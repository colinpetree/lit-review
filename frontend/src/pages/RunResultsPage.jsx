import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PageShell, BackLink } from '../components/ui'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import { EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive } from '../lib/paperFilter'
import { fetchJson, postJson } from '../lib/api'
import { driveAnalysisRun, mergeRunResults } from '../lib/driveAnalysisRun'
import { datasetLabels } from '../lib/format'
import { modelLabel } from '../lib/models'

export default function RunResultsPage() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [error, setError] = useState(null)
  const [resuming, setResuming] = useState(false)
  const [filter, setFilter] = useState(EMPTY_PAPER_FILTER)
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
    setFilter(EMPTY_PAPER_FILTER)
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

  // Throws on failure so the confirmation modal can show the error.
  const markExample = async (paper) => {
    await postJson(`/api/analysis-runs/${id}/examples`, { paper_id: paper.id })
    setRun((prev) => ({
      ...prev,
      results: prev.results.map((p) => (p.id === paper.id ? { ...p, is_example: true } : p)),
    }))
  }
  const canMarkExamples = run.prompt && !run.prompt.deleted
  const visibleResults = filterPapers(run.results, filter)

  return (
    <PageShell title={run.grading_prompt}>
      <BackLink to="/results">Back to Past Results</BackLink>

      {run.prompt ? (
        <p className="mt-4 text-sm text-gray-500">
          Prompt:{' '}
          {run.prompt.deleted ? (
            run.prompt.name
          ) : (
            <Link to={`/prompts/${run.prompt.id}`} className="text-blue-600 hover:underline">
              {run.prompt.name}
            </Link>
          )}
        </p>
      ) : null}
      <p className="mt-1 text-sm text-gray-500">
        Datasets: {datasetLabels(run.datasets).join(', ')}
      </p>
      <p className="mt-1 text-sm text-gray-500">
        {modelLabel(run.ai_api, run.ai_model)} · {run.status} · est. ${run.cost.toFixed(4)}
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

      <PaperFilterBar filter={filter} onChange={setFilter} shown={visibleResults.length} total={run.results.length} />

      {isPaperFilterActive(filter) && visibleResults.length === 0 ? (
        <p className="mt-4 text-sm text-gray-500">No papers match the current filters.</p>
      ) : null}

      <ul className="mt-4 flex flex-col gap-3">
        {visibleResults.map((paper, index) => (
          <PaperCard
            key={paper.id ?? `${paper.doi ?? paper.title}-${index}`}
            result={paper}
            onUpdate={handlePaperUpdate}
            onMarkExample={canMarkExamples ? markExample : undefined}
          />
        ))}
      </ul>
    </PageShell>
  )
}
