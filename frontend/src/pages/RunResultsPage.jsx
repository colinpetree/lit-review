import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PageShell, BackLink, Card } from '../components/ui'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import InfiniteList from '../components/InfiniteList'
import {
  DEFAULT_RUN_SORT,
  EMPTY_PAPER_FILTER,
  RUN_SORT_OPTIONS,
  filterPapers,
  isPaperFilterActive,
  sortPapers,
} from '../lib/paperFilter'
import { deleteJson, fetchJson, patchJson, postJson } from '../lib/api'
import { exportMenuItems } from '../lib/exportFile'
import { formatUsd } from '../lib/spendSetting'
import { mergeRunResults } from '../lib/runResults'
import { useJobs } from '../components/JobsProvider'
import { useSettingsModal } from '../components/SettingsModalProvider'
import { isActiveJob, isWorking, jobsFor, progressSignature, statusSignature } from '../lib/jobs'
import { datasetLabels, formatDateTime, RUN_COST_NOTE } from '../lib/format'
import { StageIndicator } from '../components/Spinner'
import ModelBadge from '../components/ModelBadge'
import RunMenu from '../components/RunMenu'

export default function RunResultsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState(null)
  // Set only when the run could not be loaded at all. Anything that goes wrong afterwards is shown
  // beside the run (actionError) and never replaces it.
  const [error, setError] = useState(null)
  const { jobs, startJob, refreshJobs } = useJobs()
  // Only this evaluation's own jobs make the page load it again: another job moving along (some other
  // evaluation, a lookup on a dataset) says nothing about what this page shows.
  const myJobs = useMemo(() => jobsFor(jobs, 'run_id', Number(id)), [jobs, id])
  const progressKey = useMemo(() => progressSignature(myJobs), [myJobs])
  const statusKey = useMemo(() => statusSignature(myJobs), [myJobs])
  const [filter, setFilter] = useState(EMPTY_PAPER_FILTER)
  const [sort, setSort] = useState(DEFAULT_RUN_SORT)
  const [actionError, setActionError] = useState(null)
  const { openSettings } = useSettingsModal()
  // /evaluations/:id is one long-lived route element - React Router doesn't remount it on a
  // param-only change, so this says which run a reload belongs to.
  const idRef = useRef(id)
  const loadedRef = useRef(false)
  const lastLoadRef = useRef(0)
  // The user's latest Read/relevance choice per paper id. The run is loaded again as it is graded, and a
  // copy can be built before a save lands and would show the old value, so every reload is re-overlaid
  // with these.
  const editsRef = useRef(new Map())
  // Same idea for a rename made while grading (the AI prompt title can also
  // change the name in a reload, until the user picks one).
  const renamedRef = useRef(null)
  const withEdits = useCallback(
    (r) => ({
      ...r,
      ...(renamedRef.current ? { name: renamedRef.current } : {}),
      results: r.results.map((p) => (editsRef.current.has(p.id) ? { ...p, ...editsRef.current.get(p.id) } : p)),
    }),
    [],
  )

  useEffect(() => {
    let cancelled = false
    idRef.current = id
    loadedRef.current = false
    editsRef.current = new Map()
    renamedRef.current = null
    setError(null)
    setRun(null)
    setFilter(EMPTY_PAPER_FILTER)
    setActionError(null)
    fetchJson(`/api/analysis-runs/${id}`)
      .then((r) => {
        if (cancelled) return
        loadedRef.current = true
        lastLoadRef.current = Date.now()
        setRun(mergeRunResults(r))
      })
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [id])

  // The run is graded in the background, so the page follows it: when a batch is graded, or the job starts,
  // stops or ends, the run is loaded again (at most every 3 seconds). A reload that fails changes nothing:
  // what is showing stays, and the next change tries again.
  const reload = useCallback(async () => {
    const forId = idRef.current
    lastLoadRef.current = Date.now()
    try {
      const latest = await fetchJson(`/api/analysis-runs/${forId}`)
      if (idRef.current === forId) setRun(withEdits(mergeRunResults(latest)))
    } catch {
      // keep what is showing
    }
  }, [withEdits])
  useEffect(() => {
    if (!loadedRef.current) return
    const wait = Math.max(0, 3000 - (Date.now() - lastLoadRef.current))
    const timer = setTimeout(reload, wait)
    return () => clearTimeout(timer)
  }, [progressKey, statusKey, reload])

  // Queue the grading of whatever is still ungraded (the work itself happens in the background). If the
  // run's spending limit stopped it, the server first raises the limit by the amount it started with:
  // the limit is a safety net, and Resume is how the user goes past it.
  const startGrading = async () => {
    setActionError(null)
    try {
      await startJob({ kind: 'run_score', run_id: Number(id), extend_limit: true })
      await reload()
    } catch (err) {
      setActionError(err.message)
    }
  }

  // Filtered, sorted and exportable lists are worked out once per change, not on every draw: a run can
  // hold hundreds of papers, and the page is drawn again whenever its job moves along.
  // Sorted first, then filtered (filtering keeps the order), so Export all follows the sort too.
  const results = run?.results
  const runId = run?.id
  const sortedResults = useMemo(() => (results ? sortPapers(results, sort) : []), [results, sort])
  const visibleResults = useMemo(() => filterPapers(sortedResults, filter), [sortedResults, filter])
  const exportItems = useMemo(
    () =>
      sortedResults.length
        ? exportMenuItems({
            url: `/api/analysis-runs/${runId}/export`,
            all: sortedResults.map((p) => p.id),
            shown: visibleResults.map((p) => p.id),
            filterActive: isPaperFilterActive(filter),
            onError: setActionError,
          })
        : [],
    [sortedResults, runId, visibleResults, filter],
  )

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

  // Grading is going on (or waiting its turn) in the background. The live job list is newer than the
  // run's own copy of its state, which is refreshed a moment after a job starts or ends.
  const liveJob = jobs.filter((j) => j.run_id === run.id && j.kind === 'run_score' && isActiveJob(j)).at(-1)
  const job = liveJob ?? (isWorking(run) ? run.job : null)
  const working = Boolean(job)
  const done = job?.progress?.done ?? Math.max(run.results.length - run.remaining, 0)
  const left = job?.progress?.remaining ?? run.remaining
  const workingLabel =
    job?.status === 'queued'
      ? 'Waiting for other work to finish…'
      : job?.stop_requested
        ? 'Stopping after this batch…'
        : `Grading papers… ${done} done, ${left} remaining`
  const canMarkExamples = run.prompt && !run.prompt.deleted
  // When it finished, or when it was started if it hasn't.
  const runDate = formatDateTime(run.completed_at || run.created_at)

  return (
    <PageShell>
      <BackLink to="/evaluations">Back to Paper Evaluations</BackLink>

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
              onError={setActionError}
              onDelete={async () => {
                await deleteJson(`/api/analysis-runs/${run.id}`)
                refreshJobs()
                navigate('/evaluations')
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
              {formatUsd(run.scoring_cost)} used of {formatUsd(run.max_usd)} allowed
            </p>
          </div>
        ) : null}

        {working ? (
          <div className="flex flex-col gap-1">
            <StageIndicator label={workingLabel} />
            {job?.progress?.note ? <p className="text-xs text-gray-400">{job.progress.note}</p> : null}
          </div>
        ) : run.remaining > 0 ? (
          <div className="flex flex-col items-start gap-2">
            {run.limit_reached ? (
              <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
                This run reached its{' '}
                <button
                  type="button"
                  onClick={() => openSettings('ai')}
                  title="Settings: the limit new evaluations start with"
                  className="text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
                >
                  spending limit
                </button>{' '}
                of {formatUsd(run.max_usd)} ({formatUsd(run.scoring_cost)} spent).{' '}
                {run.remaining.toLocaleString()} paper{run.remaining === 1 ? ' is' : 's are'} not graded yet; everything
                graded so far is kept.{' '}
                {run.next_limit != null
                  ? `Resume grading raises this run's limit to ${formatUsd(run.next_limit)} and carries on.`
                  : 'It is already at the highest limit there is.'}
              </p>
            ) : run.state === 'incomplete' && run.job?.error ? (
              <p className="text-sm text-amber-700 dark:text-amber-400">{run.job.error}</p>
            ) : null}
            <button
              type="button"
              onClick={startGrading}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
            >
              {run.status === 'completed'
                ? // Papers came back (or were added) after the run finished.
                  `Grade ${run.remaining} new paper${run.remaining === 1 ? '' : 's'}`
                : `Resume grading (${run.remaining} ungraded)`}
            </button>
          </div>
        ) : null}
      </Card>

      <PaperFilterBar
        filter={filter}
        onChange={setFilter}
        shown={visibleResults.length}
        total={run.results.length}
        sort={sort}
        onSortChange={setSort}
        sortOptions={RUN_SORT_OPTIONS}
        showRelevance
      />

      {actionError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{actionError}</p> : null}

      {isPaperFilterActive(filter) && visibleResults.length === 0 ? (
        <p className="mt-4 text-sm text-gray-500">No papers match the current filters.</p>
      ) : null}

      <InfiniteList
        className="mt-4 flex flex-col gap-3"
        items={visibleResults}
        resetKey={JSON.stringify([run.id, filter, sort])}
        renderItem={(paper, index) => (
          <PaperCard
            key={paper.id ?? `${paper.doi ?? paper.title}-${index}`}
            result={paper}
            onUpdate={handlePaperUpdate}
            onMarkExample={canMarkExamples ? markExample : undefined}
            onToggleRead={toggleRead}
            onSetRelevance={setRelevance}
          />
        )}
      />
    </PageShell>
  )
}
