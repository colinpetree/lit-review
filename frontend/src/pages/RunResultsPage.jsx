import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PageShell, BackLink } from '../components/ui'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import { EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive } from '../lib/paperFilter'
import { fetchJson, patchJson, postJson } from '../lib/api'
import { driveAnalysisRun, mergeRunResults } from '../lib/driveAnalysisRun'
import { datasetLabels, formatDateTime } from '../lib/format'
import ModelBadge from '../components/ModelBadge'

export default function RunResultsPage() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [error, setError] = useState(null)
  const [resuming, setResuming] = useState(false)
  const [filter, setFilter] = useState(EMPTY_PAPER_FILTER)
  const [actionError, setActionError] = useState(null)
  // /results/:id is one long-lived route element - React Router doesn't
  // remount it on a param-only change, so a "Resume scoring" loop started
  // on one run keeps running (and keeps calling setRun) even after the
  // user navigates to a different run's id. Aborting the leftover request
  // when id changes stops both the stale network calls and the stale
  // setRun calls that would otherwise overwrite the newly-loaded run.
  const activeRequestRef = useRef(null)
  // The user's latest Read/relevance choice per paper id. A scoring response
  // can be built before a save lands and would show the old value, so every
  // scoring update is re-overlaid with these.
  const editsRef = useRef(new Map())
  const withEdits = (r) => ({
    ...r,
    results: r.results.map((p) => (editsRef.current.has(p.id) ? { ...p, ...editsRef.current.get(p.id) } : p)),
  })

  useEffect(() => {
    let cancelled = false
    activeRequestRef.current?.abort()
    editsRef.current = new Map()
    setError(null)
    setRun(null)
    setResuming(false)
    setFilter(EMPTY_PAPER_FILTER)
    setActionError(null)
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
        if (!controller.signal.aborted) setRun(withEdits(updated))
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

  // Shows a Read/relevance change immediately and remembers it (see editsRef).
  const applyEdit = (paperId, patch) => {
    editsRef.current.set(paperId, { ...editsRef.current.get(paperId), ...patch })
    setRun((prev) => ({
      ...prev,
      results: prev.results.map((p) => (p.id === paperId ? { ...p, ...patch } : p)),
    }))
  }

  // Read is global to the paper. Optimistic, reverting if the save fails.
  const toggleRead = async (paper) => {
    setActionError(null)
    const previous = Boolean(paper.read)
    applyEdit(paper.id, { read: !previous })
    try {
      await patchJson(`/api/papers/${paper.id}`, { read: !previous })
    } catch (err) {
      applyEdit(paper.id, { read: previous })
      setActionError(err.message)
    }
  }

  // Optimistic, reverting if the save fails.
  const setRelevance = async (paper, relevance) => {
    setActionError(null)
    const previous = paper.relevance || 'neutral'
    applyEdit(paper.id, { relevance })
    try {
      await patchJson(`/api/analysis-runs/${id}/results/${paper.id}`, { relevance })
    } catch (err) {
      applyEdit(paper.id, { relevance: previous })
      setActionError(err.message)
    }
  }

  const canMarkExamples = run.prompt && !run.prompt.deleted
  const visibleResults = filterPapers(run.results, filter)
  // When it finished, or when it was started if it hasn't.
  const runDate = formatDateTime(run.completed_at || run.created_at)

  return (
    <PageShell title={run.prompt?.name || run.grading_prompt}>
      <BackLink to="/results">Back to Analysis Results</BackLink>

      {run.prompt ? (
        <p className="mt-4 text-sm text-gray-500">
          Prompt:{' '}
          {run.prompt.deleted ? (
            run.prompt.name
          ) : (
            <Link
              to={`/prompts/${run.prompt.id}`}
              className="text-blue-600 transition-colors hover:text-blue-800"
            >
              {run.prompt.name}
            </Link>
          )}
        </p>
      ) : null}
      {/* A flex row, so wrapped lines line up under the text, not the label. */}
      <p className="mt-1 flex gap-1 text-sm text-gray-500">
        <span className="shrink-0">Criteria:</span>
        <span className="min-w-0 whitespace-pre-line">{run.grading_prompt}</span>
      </p>
      <p className="mt-1 text-sm text-gray-500">
        Datasets:{' '}
        {datasetLabels(run.datasets).map((label, i) => {
          const dataset = run.datasets[i]
          return (
            <span key={dataset.id}>
              {i > 0 ? ', ' : ''}
              {dataset.deleted ? (
                label
              ) : (
                <Link
                  to={`/datasets/${dataset.id}`}
                  className="text-blue-600 transition-colors hover:text-blue-800"
                >
                  {label}
                </Link>
              )}
            </span>
          )
        })}
        {` · ${run.results.length} paper${run.results.length === 1 ? '' : 's'}`}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-gray-500">
        <ModelBadge aiApi={run.ai_api} aiModel={run.ai_model} cost={run.cost} className="text-gray-500" />
        <span>
          · {run.status}
          {runDate ? ` · ${runDate}` : ''}
        </span>
      </div>

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

      <PaperFilterBar
        filter={filter}
        onChange={setFilter}
        shown={visibleResults.length}
        total={run.results.length}
        showRelevance
      />

      {actionError ? <p className="mt-3 text-sm text-red-600">{actionError}</p> : null}

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
            onToggleRead={toggleRead}
            onSetRelevance={setRelevance}
          />
        ))}
      </ul>
    </PageShell>
  )
}
