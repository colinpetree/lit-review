import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PageShell, BackLink, Card } from '../components/ui'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import { EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive } from '../lib/paperFilter'
import { deleteJson, fetchJson, patchJson, postJson } from '../lib/api'
import { exportMenuItems } from '../lib/exportFile'
import { formatUsd } from '../lib/spendSetting'
import { driveAnalysisRun, mergeRunResults } from '../lib/driveAnalysisRun'
import { datasetLabels, formatDateTime, RUN_COST_NOTE } from '../lib/format'
import ModelBadge from '../components/ModelBadge'
import RunMenu from '../components/RunMenu'

export default function RunResultsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState(null)
  const [error, setError] = useState(null)
  const [resuming, setResuming] = useState(false)
  const [filter, setFilter] = useState(EMPTY_PAPER_FILTER)
  const [actionError, setActionError] = useState(null)
  // What the user has typed as the new spending limit (null: show the suggestion).
  const [limitInput, setLimitInput] = useState(null)
  const [raising, setRaising] = useState(false)
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
    setLimitInput(null)
    setRaising(false)
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
      if (err.limitReached) {
        // Not a failure: the run is paused at its spending limit. Reload it so the page
        // shows that (and what is left), instead of replacing the page with an error.
        try {
          const latest = await fetchJson(`/api/analysis-runs/${id}`)
          if (!controller.signal.aborted) setRun(withEdits(mergeRunResults(latest)))
        } catch (reloadErr) {
          if (!controller.signal.aborted) setActionError(reloadErr.message)
        }
      } else if (err.name !== 'AbortError') {
        setError(err.message)
      }
    } finally {
      if (!controller.signal.aborted) setResuming(false)
    }
  }

  // Raise a run's spending limit and carry on scoring.
  const raiseLimit = async (amount) => {
    setActionError(null)
    setRaising(true)
    try {
      await patchJson(`/api/analysis-runs/${id}`, { max_usd: amount })
      setRun((prev) => ({ ...prev, max_usd: amount, limit_reached: false }))
      setLimitInput(null)
    } catch (err) {
      setActionError(err.message)
      return
    } finally {
      setRaising(false)
    }
    await resumeScoring()
  }

  if (error) {
    return (
      <PageShell title="Run Results">
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
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
  const exportItems = run.results.length
    ? exportMenuItems({
        url: `/api/analysis-runs/${run.id}/export`,
        all: run.results.map((p) => p.id),
        shown: visibleResults.map((p) => p.id),
        filterActive: isPaperFilterActive(filter),
        onError: setActionError,
      })
    : []
  // When it finished, or when it was started if it hasn't.
  const runDate = formatDateTime(run.completed_at || run.created_at)

  return (
    <PageShell>
      <BackLink to="/results">Back to Results</BackLink>

      <Card className="mt-4 flex flex-col gap-5">
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl font-semibold text-gray-800">
            {run.name || run.prompt?.name || run.grading_prompt}
          </h1>
          <div className="shrink-0">
            <RunMenu
              run={run}
              extraItems={exportItems}
              onRenamed={(name) => {
                renamedRef.current = name
                setRun((prev) => ({ ...prev, name }))
              }}
              onDelete={async () => {
                activeRequestRef.current?.abort()
                await deleteJson(`/api/analysis-runs/${run.id}`)
                navigate('/results')
              }}
            />
          </div>
        </div>

        {run.prompt ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">Prompt</p>
            <p className="text-sm text-gray-800">
              {run.prompt.deleted ? (
                run.prompt.name
              ) : (
                <Link
                  to={`/prompts/${run.prompt.id}`}
                  className="text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
                >
                  {run.prompt.name}
                </Link>
              )}
            </p>
          </div>
        ) : null}

        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">Criteria</p>
          <p className="whitespace-pre-line text-sm text-gray-800">{run.grading_prompt}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">Datasets</p>
          <p className="text-sm text-gray-800">
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
                      className="text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
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
          <p className="text-sm text-gray-800">{run.results.length}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">AI model</p>
          <ModelBadge
            aiApi={run.ai_api}
            aiModel={run.ai_model}
            cost={run.cost}
            costNote={RUN_COST_NOTE}
            className="text-sm text-gray-800"
          />
        </div>

        {runDate ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">{run.completed_at ? 'Completed' : 'Created'}</p>
            <p className="text-sm text-gray-800">{runDate}</p>
          </div>
        ) : null}

        {run.retracted_left_out > 0 ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">Retracted papers</p>
            <p className="text-sm text-gray-800">
              {run.retracted_left_out} retracted paper{run.retracted_left_out === 1 ? ' was' : 's were'} left out of
              this evaluation.
            </p>
          </div>
        ) : null}

        {run.max_usd != null ? (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">Spending limit</p>
            <p className="text-sm text-gray-800">
              {formatUsd(run.max_usd)} for scoring, {formatUsd(run.scoring_cost)} spent so far. A limit is checked
              before each batch of 20 papers, so a run can pass it by up to one batch.
            </p>
          </div>
        ) : null}

        {run.limit_reached ? (
          <div className="flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 dark:border-amber-800 dark:bg-amber-950/30">
            <p className="text-sm text-amber-900 dark:text-amber-200">
              Scoring paused: this run reached its spending limit of {formatUsd(run.max_usd)}.{' '}
              {run.remaining.toLocaleString()} paper{run.remaining === 1 ? ' is' : 's are'} not scored yet. Everything
              scored so far is kept.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="new-limit" className="text-sm text-amber-900 dark:text-amber-200">
                New limit ($)
              </label>
              <input
                id="new-limit"
                value={limitInput ?? (Math.ceil(run.max_usd * 2 * 100) / 100).toFixed(2)}
                onChange={(e) => setLimitInput(e.target.value)}
                inputMode="decimal"
                className="w-24 rounded-md border border-gray-300 bg-surface px-2 py-1 text-sm"
              />
              <button
                type="button"
                disabled={raising || resuming || !(Number(limitInput ?? run.max_usd * 2) > run.scoring_cost)}
                onClick={() => raiseLimit(Number(limitInput ?? Math.ceil(run.max_usd * 2 * 100) / 100))}
                className="rounded-md border border-gray-300 bg-surface px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
              >
                Raise limit and continue
              </button>
            </div>
          </div>
        ) : null}

        {run.remaining > 0 && !run.limit_reached ? (
          <button
            type="button"
            onClick={resumeScoring}
            disabled={resuming}
            className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            {resuming
              ? `Scoring… ${run.remaining} remaining`
              : run.status === 'completed'
                ? // Papers came back (or were added) after the run finished.
                  `Score ${run.remaining} new paper${run.remaining === 1 ? '' : 's'}`
                : `Resume scoring (${run.remaining} unscored)`}
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

      {actionError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{actionError}</p> : null}

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
