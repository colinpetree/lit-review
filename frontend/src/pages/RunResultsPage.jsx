import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PageShell, BackLink, Card } from '../components/ui'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import { EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive } from '../lib/paperFilter'
import { fetchJson, patchJson, postJson } from '../lib/api'
import { driveAnalysisRun, mergeRunResults } from '../lib/driveAnalysisRun'
import { datasetLabels, formatDateTime } from '../lib/format'
import ModelBadge from '../components/ModelBadge'
import RunMenu from '../components/RunMenu'

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
  // Same idea for a rename made while scoring (the AI prompt title can also
  // change the name in a scoring response, until the user picks one).
  const renamedRef = useRef(null)
  const withEdits = (r) => ({
    ...r,
    ...(renamedRef.current ? { name: renamedRef.current } : {}),
    results: r.results.map((p) => (editsRef.current.has(p.id) ? { ...p, ...editsRef.current.get(p.id) } : p)),
  })

  useEffect(() => {
    let cancelled = false
    activeRequestRef.current?.abort()
    editsRef.current = new Map()
    renamedRef.current = null
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
    <PageShell>
      <BackLink to="/results">Back to Analysis Results</BackLink>

      <Card className="mt-4 flex flex-col gap-5">
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl font-semibold text-gray-900">
            {run.name || run.prompt?.name || run.grading_prompt}
          </h1>
          <div className="shrink-0">
            <RunMenu
              run={run}
              onRenamed={(name) => {
                renamedRef.current = name
                setRun((prev) => ({ ...prev, name }))
              }}
            />
          </div>
        </div>

        {run.prompt ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">Prompt</p>
            <p className="text-sm text-gray-900">
              {run.prompt.deleted ? (
                run.prompt.name
              ) : (
                <Link
                  to={`/prompts/${run.prompt.id}`}
                  className="text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline"
                >
                  {run.prompt.name}
                </Link>
              )}
            </p>
          </div>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">Criteria</p>
          <p className="whitespace-pre-line text-sm text-gray-900">{run.grading_prompt}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">Datasets</p>
          <p className="text-sm text-gray-900">
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
                      className="text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline"
                    >
                      {label}
                    </Link>
                  )}
                </span>
              )
            })}
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">Papers</p>
          <p className="text-sm text-gray-900">{run.results.length}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">AI model</p>
          <ModelBadge aiApi={run.ai_api} aiModel={run.ai_model} cost={run.cost} className="text-sm text-gray-900" />
        </div>

        {runDate ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">{run.completed_at ? 'Completed' : 'Created'}</p>
            <p className="text-sm text-gray-900">{runDate}</p>
          </div>
        ) : null}

        {run.remaining > 0 ? (
          <button
            type="button"
            onClick={resumeScoring}
            disabled={resuming}
            className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            {resuming ? `Scoring… ${run.remaining} remaining` : `Resume scoring (${run.remaining} unscored)`}
          </button>
        ) : null}
      </Card>

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
