import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { PageShell, Card, BackLink } from '../components/ui'
import Spinner, { StageIndicator } from '../components/Spinner'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import InfiniteList from '../components/InfiniteList'
import { DEFAULT_PAPER_SORT, EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive, sortPapers } from '../lib/paperFilter'
import DatasetMenu from '../components/DatasetMenu'
import ModelBadge from '../components/ModelBadge'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import { deleteJson, fetchJson, patchJson } from '../lib/api'
import { exportMenuItems } from '../lib/exportFile'
import JobStatus from '../components/JobStatus'
import { useJobs } from '../components/JobsProvider'
import { isActiveJob, jobsFor, progressSignature, progressText, statusSignature } from '../lib/jobs'
import { sourceIcon, sourceLabel } from '../lib/paperSources'
import { formatDateTime, formatYearRange } from '../lib/format'
import { summarizeRetrieval } from '../lib/retrieval'
import SearchCompletenessModal from '../components/SearchCompletenessModal'
import { useSettingsModal } from '../components/SettingsModalProvider'

// Whether every paper the sources reported for the searches was retrieved, with the
// numbers per source and search behind it. A search that stopped short says why,
// so the user knows to narrow it rather than assume nothing was missed.
function RetrievalCompleteness({ retrieval, onShowDetails }) {
  const summary = summarizeRetrieval(retrieval)
  if (!summary) return null
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-sm font-medium text-gray-500">Search completeness</p>
      {summary.complete ? (
        <p className="text-sm text-gray-800">Every paper the sources reported for these searches was kept.</p>
      ) : null}
      <button
        type="button"
        onClick={onShowDetails}
        className="self-start text-sm text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
      >
        Show details
      </button>
    </div>
  )
}

// The dataset's title (renamed from its dots menu, like an analysis run's) and
// the details it was retrieved with (all fixed).
function DatasetDetailsCard({ dataset, onRenamed, onDelete, onError, onShowCompleteness, menuItems }) {
  return (
    <Card className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold text-gray-800">{dataset.name}</h1>
        <div className="shrink-0">
          <DatasetMenu
            dataset={dataset}
            onRenamed={onRenamed}
            onDelete={onDelete}
            onError={onError}
            extraItems={menuItems}
          />
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-500">Dataset topic</p>
        <p className="whitespace-pre-wrap text-sm text-gray-800">{dataset.verbose_query}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-500">Paper sources</p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-800">
          {dataset.sources.map((id) => {
            const Icon = sourceIcon(id)
            return (
              <span key={id} className="flex items-center gap-2">
                {Icon ? <Icon size={14} className="shrink-0" /> : null}
                {sourceLabel(id)}
              </span>
            )
          })}
        </div>
      </div>

      <RetrievalCompleteness retrieval={dataset.retrieval} onShowDetails={onShowCompleteness} />

      {dataset.expansion ? (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-500">AI model</p>
          <ModelBadge
            aiApi={dataset.expansion.ai_api}
            aiModel={dataset.expansion.ai_model}
            cost={dataset.expansion.cost}
            className="text-sm text-gray-800"
          />
        </div>
      ) : null}

      {/* Updated (the latest check for new papers) sits to the left of Created, which
          always stays: creation is never replaced by a later check. */}
      <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-5">
        <div className="flex flex-wrap gap-x-10 gap-y-5">
          {dataset.last_refresh ? (
            <div className="flex flex-col gap-1.5">
              <p className="text-sm font-medium text-gray-500">Updated</p>
              <p className="text-sm text-gray-800">{formatDateTime(dataset.last_refresh.at)}</p>
            </div>
          ) : null}
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-medium text-gray-500">Created</p>
            <p className="text-sm text-gray-800">{formatDateTime(dataset.created_at)}</p>
          </div>
        </div>
        {/* Just the state here: how far a lookup has got is on the Missing Abstracts card. */}
        <JobStatus item={dataset} showProgress={false} className="ml-auto" />
      </div>
    </Card>
  )
}

// Publishers whose abstracts can only be looked up with the user's own API key.
const PUBLISHER_LOOKUPS = [
  { label: 'Elsevier', key: 'elsevier' },
  { label: 'Springer Nature', key: 'springernature' },
]

const isMissingAbstract = (p) => !p.excluded && !(p.abstract || '').trim() && Boolean(p.doi)
// Missing an abstract, has a DOI to look up, and no lookup has completed for it yet.
const isLookupCandidate = (p) => isMissingAbstract(p) && !p.abstract_checked

// A dataset is pure retrieval - never joined to any analysis run here.
// Grades only ever appear on the Paper Evaluations side; a
// paper on this page is always shown exactly as retrieved, with no grade.
//
// Searching, checking for new papers and looking up abstracts all happen in the background (see
// backend/jobs.py), whatever page is open. This page follows them: it loads the dataset again, quietly,
// as they move along, and shows what they say.
export default function DatasetDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { openSettings } = useSettingsModal()
  const providers = useConfiguredProviders()
  const { jobs, startJob, resumeJob, refreshJobs } = useJobs()
  // Only this dataset's own jobs make the page load it again: another job moving along (an evaluation, a
  // lookup on some other dataset) says nothing about what this page shows, and a dataset can hold
  // thousands of papers.
  const myJobs = useMemo(() => jobsFor(jobs, 'dataset_id', Number(id)), [jobs, id])
  const progressKey = useMemo(() => progressSignature(myJobs), [myJobs])
  const statusKey = useMemo(() => statusSignature(myJobs), [myJobs])
  const [dataset, setDataset] = useState(null)
  // Set only when the dataset could not be loaded at all. Anything that goes wrong afterwards is shown
  // beside the dataset and never replaces it.
  const [error, setError] = useState(null)
  const [toggleError, setToggleError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_PAPER_FILTER)
  const [sort, setSort] = useState(DEFAULT_PAPER_SORT)
  const [jobError, setJobError] = useState(null)
  // The Search completeness dialog (the numbers behind the summary on the details card).
  const [showCompleteness, setShowCompleteness] = useState(false)
  // The page is reused when the user opens another dataset, so this says which one a reload belongs to.
  const idRef = useRef(id)
  const loadedRef = useRef(false)
  const lastLoadRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    idRef.current = id
    loadedRef.current = false
    setError(null)
    setToggleError(null)
    setJobError(null)
    setShowCompleteness(false)
    setFilter(EMPTY_PAPER_FILTER)
    setDataset(null)
    fetchJson(`/api/datasets/${id}`)
      .then((d) => {
        if (cancelled) return
        loadedRef.current = true
        lastLoadRef.current = Date.now()
        setDataset(d)
      })
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [id])

  // Loads the dataset again, without any loading state. A reload that fails changes nothing: what is
  // showing stays, and the next change tries again.
  const reload = useCallback(async () => {
    const forId = idRef.current
    lastLoadRef.current = Date.now()
    try {
      const latest = await fetchJson(`/api/datasets/${forId}`)
      if (idRef.current === forId) setDataset(latest)
    } catch {
      // keep what is showing
    }
  }, [])

  // As the background work moves along (an abstract found, a search finished) or starts and ends, the
  // dataset is loaded again, at most every 3 seconds.
  useEffect(() => {
    if (!loadedRef.current) return
    const wait = Math.max(0, 3000 - (Date.now() - lastLoadRef.current))
    const timer = setTimeout(reload, wait)
    return () => clearTimeout(timer)
  }, [progressKey, statusKey, reload])

  // Filtered, sorted and exportable lists are worked out once per change, not on every draw (the page is
  // drawn again whenever one of its jobs moves along).
  // Sorted first, then filtered (filtering keeps the order), so Export all follows the sort too.
  const papers = dataset?.papers
  const sortedPapers = useMemo(() => (papers ? sortPapers(papers, sort) : []), [papers, sort])
  const visiblePapers = useMemo(() => filterPapers(sortedPapers, filter), [sortedPapers, filter])
  const datasetId = dataset?.id
  const exportItems = useMemo(() => {
    const included = sortedPapers.filter((p) => !p.excluded)
    if (!included.length) return []
    return exportMenuItems({
      url: `/api/datasets/${datasetId}/export`,
      all: included.map((p) => p.id),
      shown: visiblePapers.filter((p) => !p.excluded).map((p) => p.id),
      filterActive: isPaperFilterActive(filter),
      onError: setToggleError,
    })
  }, [sortedPapers, datasetId, visiblePapers, filter])

  const queue = async (fields) => {
    setJobError(null)
    try {
      await startJob(fields)
      await reload()
    } catch (err) {
      setJobError(err.message)
    }
  }

  if (error) {
    return (
      <PageShell title="Paper Dataset">
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      </PageShell>
    )
  }
  if (!dataset) {
    return (
      <PageShell title="Paper Dataset">
        <p className="text-sm text-gray-500">Loading…</p>
      </PageShell>
    )
  }

  // The jobs working on this dataset, newest last. The live list is newer than the dataset's own copy.
  const mine = myJobs
  const latestOf = (kind) => mine.filter((j) => j.kind === kind).at(-1) ?? null
  const searchJob = latestOf('dataset_search') ?? (dataset.pending ? dataset.job : null)
  const refreshJob = latestOf('dataset_refresh')
  const lookupJob = latestOf('find_abstracts')
  const refreshing = Boolean(refreshJob && isActiveJob(refreshJob))
  const lookingUp = Boolean(lookupJob && isActiveJob(lookupJob))

  const handlePaperUpdate = (updated) => {
    setDataset((prev) => ({
      ...prev,
      papers: prev.papers.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)),
    }))
  }

  const toggleExclude = async (paper) => {
    setToggleError(null)
    try {
      const updated = await patchJson(`/api/datasets/${dataset.id}/papers/${paper.id}`, {
        excluded: !paper.excluded,
      })
      setDataset((prev) => ({
        ...prev,
        papers: prev.papers.map((p) => (p.id === paper.id ? { ...p, excluded: updated.excluded } : p)),
      }))
    } catch (err) {
      setToggleError(err.message)
    }
  }

  // Read is global to the paper; the response carries the saved state.
  const toggleRead = async (paper) => {
    setToggleError(null)
    try {
      const updated = await patchJson(`/api/papers/${paper.id}`, { read: !paper.read })
      handlePaperUpdate(updated)
    } catch (err) {
      setToggleError(err.message)
    }
  }

  const detailsCard = (
    <DatasetDetailsCard
      dataset={dataset}
      onRenamed={(name) => setDataset((prev) => ({ ...prev, name }))}
      onDelete={async () => {
        await deleteJson(`/api/datasets/${dataset.id}`)
        refreshJobs()
        navigate('/datasets')
      }}
      onError={setToggleError}
      onShowCompleteness={() => setShowCompleteness(true)}
      menuItems={dataset.pending ? [] : exportItems}
    />
  )

  // A dataset whose search has not finished has no papers yet: say how the search is going.
  if (dataset.pending) {
    const state = searchJob ? (searchJob.status === 'incomplete' ? 'incomplete' : 'working') : 'incomplete'
    return (
      <PageShell>
        <BackLink to="/datasets">Back to Paper Datasets</BackLink>
        <div className="mt-4">
          {detailsCard}
          <div className="mt-6">
            {state === 'working' ? (
              <StageIndicator
                label={
                  searchJob.status === 'queued'
                    ? 'Waiting for other work to finish…'
                    : searchJob.stop_requested
                      ? 'Stopping…'
                      : `${progressText(searchJob) ?? 'Searching for papers…'}`
                }
              />
            ) : (
              <div className="flex flex-col items-start gap-2">
                <p className="text-sm text-amber-700 dark:text-amber-400">
                  {searchJob?.error ?? 'This search did not finish.'}
                </p>
                {searchJob ? (
                  <button
                    type="button"
                    onClick={() => resumeJob(searchJob.id).then(reload).catch((err) => setJobError(err.message))}
                    className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
                  >
                    Resume search
                  </button>
                ) : null}
              </div>
            )}
            {jobError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{jobError}</p> : null}
            {toggleError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{toggleError}</p> : null}
          </div>
          {showCompleteness ? (
            <SearchCompletenessModal dataset={dataset} onClose={() => setShowCompleteness(false)} />
          ) : null}
        </div>
      </PageShell>
    )
  }

  // The publishers whose abstracts need an API key that isn't saved yet.
  const keylessPublishers = PUBLISHER_LOOKUPS.filter((p) => !providers?.[p.key]).map((p) => p.label)

  const missingAbstracts = dataset.papers.filter(isMissingAbstract).length
  // Papers a lookup can still try, vs ones every source was already asked about.
  const lookupCandidates = dataset.papers.filter(isLookupCandidate).length
  const unfindable = missingAbstracts - lookupCandidates

  const includedCount = dataset.papers.filter((p) => !p.excluded).length
  const excludedCount = dataset.papers.length - includedCount

  // How the latest check for new papers went, if it stopped short of some papers.
  const lastCheck = summarizeRetrieval(dataset.last_refresh?.retrieval)
  const incompleteCheck = lastCheck && !lastCheck.complete ? lastCheck : null

  const yearRange = formatYearRange(dataset.oldest_year, dataset.newest_year, dataset.newest_publication_date)

  // What the lookup job reports (kept for ten minutes after it ends).
  const lookupProgress = lookupJob?.progress ?? {}
  const lookupResultShown = lookupJob && !isActiveJob(lookupJob)

  // The abstract lookup panel is hidden once every included paper with a DOI
  // has an abstract (and nothing is running).
  const showLookupPanel = missingAbstracts > 0 || lookingUp

  const newCount = refreshJob?.status === 'completed' ? refreshJob.progress?.new_count : undefined

  return (
    <PageShell>
      <BackLink to="/datasets">Back to Paper Datasets</BackLink>

      <div className="relative mt-4">
        {detailsCard}

        <div className="mt-6 flex items-center justify-between gap-4">
          <p className="text-sm text-gray-500">
            {includedCount} paper{includedCount === 1 ? '' : 's'}
            {excludedCount ? ` (${excludedCount} excluded)` : ''}
            {yearRange ? ` · ${yearRange}` : ''}
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => queue({ kind: 'dataset_refresh', dataset_id: dataset.id })}
              disabled={refreshing}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              Check for new papers
            </button>
            <button
              type="button"
              onClick={() => navigate(`/evaluations?new=1&dataset=${dataset.id}`)}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
            >
              Evaluate Dataset
            </button>
          </div>
        </div>

        {refreshing ? (
          <div className="mt-3">
            <StageIndicator
              label={
                refreshJob.status === 'queued'
                  ? 'A check for new papers is waiting for other work to finish…'
                  : 'Checking the paper sources for new papers…'
              }
            />
          </div>
        ) : null}
        {jobError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{jobError}</p> : null}
        {refreshJob?.status === 'incomplete' ? (
          <p className="mt-3 text-sm text-red-600 dark:text-red-400">{refreshJob.error}</p>
        ) : null}
        {newCount !== undefined && !refreshing ? (
          <p className="mt-3 text-sm text-gray-700">
            {newCount === 0
              ? 'No new papers found.'
              : `Found ${newCount} new paper${newCount === 1 ? '' : 's'}, marked New below.`}
          </p>
        ) : null}
        {incompleteCheck ? (
          <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
            The last check matched more papers than were kept.{' '}
            <button
              type="button"
              onClick={() => setShowCompleteness(true)}
              className="underline underline-offset-2 hover:no-underline"
            >
              Show details
            </button>
          </p>
        ) : null}
        {showCompleteness ? (
          <SearchCompletenessModal dataset={dataset} onClose={() => setShowCompleteness(false)} />
        ) : null}

        {/* On a wide window this sits just outside the right edge of the
            content column and stays in view while the paper list scrolls, so
            the column never moves whether it is shown or not. The breakpoint is
            where the sidebar, the column and this panel all fit; on a narrower
            window it takes its place in the page, above the paper list. */}
        {showLookupPanel ? (
          <aside className="mt-6 min-[1560px]:absolute min-[1560px]:inset-y-0 min-[1560px]:left-full min-[1560px]:mt-0 min-[1560px]:ml-6 min-[1560px]:w-64">
            <div className="rounded-lg border border-gray-200 bg-surface p-4 shadow-sm min-[1560px]:sticky min-[1560px]:top-6">
              <h2 className="mb-3 text-lg font-semibold text-gray-800">Missing Abstracts</h2>
              {lookingUp ? (
                <>
                  <div className="flex items-center gap-2 text-sm text-gray-700">
                    <Spinner />
                    <span>
                      {lookupJob.status === 'queued'
                        ? 'Waiting for other work to finish…'
                        : !lookupProgress.total
                          ? 'Looking up abstracts…'
                          : `Looking up abstracts… ${lookupProgress.attempted ?? 0} of ${lookupProgress.total}`}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-gray-700">It carries on in the background, whatever page you are on.</p>
                </>
              ) : lookupCandidates > 0 ? (
                <button
                  type="button"
                  onClick={() => queue({ kind: 'find_abstracts', dataset_id: dataset.id })}
                  className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
                >
                  Find missing abstracts ({lookupCandidates})
                </button>
              ) : null}

              {lookupResultShown && lookupJob.status === 'completed' ? (
                <p className="mt-3 text-sm text-gray-700">
                  {lookupProgress.filled > 0
                    ? `Found ${lookupProgress.filled} abstract${lookupProgress.filled === 1 ? '' : 's'}.`
                    : 'No new abstracts found.'}
                </p>
              ) : null}
              {!lookingUp && unfindable > 0 ? (
                <p className="mt-2 text-sm text-gray-700">
                  {unfindable} paper{unfindable === 1 ? ' has' : 's have'} no abstract in any source checked.
                </p>
              ) : null}
              {lookupProgress.no_doi > 0 ? (
                <p className="mt-2 text-xs text-gray-500">
                  {lookupProgress.no_doi} other paper{lookupProgress.no_doi === 1 ? ' has' : 's have'} no DOI, so can’t
                  be looked up.
                </p>
              ) : null}
              {Object.entries(lookupProgress.source_errors ?? {}).map(([source, message]) => (
                <p key={source} className="mt-2 text-xs text-amber-700 dark:text-amber-400">
                  {message}
                </p>
              ))}
              {lookupJob?.status === 'incomplete' ? (
                <p className="mt-2 text-sm text-red-600 dark:text-red-400">{lookupJob.error}</p>
              ) : null}

              <p className="mt-3 text-xs text-gray-400">
                {!providers ? (
                  'Missing abstracts are looked up automatically.'
                ) : keylessPublishers.length === 0 ? (
                  'The remaining papers without abstracts require manual updating. You can open the paper DOI link and copy the abstract into the paper entry on this page.'
                ) : (
                  <>
                    Missing abstracts are looked up automatically. Add {keylessPublishers.join(' and ')} API{' '}
                    {keylessPublishers.length === 1 ? 'key' : 'keys'} in{' '}
                    <button type="button" onClick={() => openSettings('databases')} className="underline">
                      Settings
                    </button>{' '}
                    to find more, or you can update them manually.
                  </>
                )}
              </p>
              {missingAbstracts > 0 ? (
                <button
                  type="button"
                  onClick={() => setFilter((f) => ({ ...f, missingAbstractOnly: true }))}
                  className="mt-3 text-sm text-blue-600 underline-offset-2 transition-colors hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
                >
                  Filter for missing abstracts
                </button>
              ) : null}
            </div>
          </aside>
        ) : null}

        {toggleError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{toggleError}</p> : null}

        <PaperFilterBar
          filter={filter}
          onChange={setFilter}
          shown={visiblePapers.length}
          total={dataset.papers.length}
          sort={sort}
          onSortChange={setSort}
          showNew={Boolean(dataset.last_refresh)}
        />

        {isPaperFilterActive(filter) && visiblePapers.length === 0 ? (
          <p className="mt-4 text-sm text-gray-500">No papers match the current filters.</p>
        ) : null}

        <InfiniteList
          className="mt-4 flex flex-col gap-3"
          items={visiblePapers}
          resetKey={JSON.stringify([dataset.id, filter, sort])}
          renderItem={(paper, index) => (
            <PaperCard
              key={paper.id ?? `${paper.doi ?? paper.title}-${index}`}
              result={paper}
              onUpdate={handlePaperUpdate}
              onToggleExclude={toggleExclude}
              onToggleRead={toggleRead}
            />
          )}
        />
      </div>
    </PageShell>
  )
}
