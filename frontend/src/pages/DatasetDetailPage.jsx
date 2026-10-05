import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PageShell, Card, BackLink } from '../components/ui'
import Spinner, { StageIndicator } from '../components/Spinner'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import InfiniteList from '../components/InfiniteList'
import { DEFAULT_PAPER_SORT, EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive, sortPapers } from '../lib/paperFilter'
import DatasetMenu from '../components/DatasetMenu'
import ModelBadge from '../components/ModelBadge'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import { deleteJson, fetchJson, patchJson, postJson } from '../lib/api'
import { exportMenuItems } from '../lib/exportFile'
import { getLookup, startLookup, subscribeLookup } from '../lib/findAbstracts'
import { sourceIcon, sourceLabel } from '../lib/paperSources'
import { formatDateTime, formatYearRange } from '../lib/format'
import { summarizeRetrieval } from '../lib/retrieval'
import SearchCompletenessModal from '../components/SearchCompletenessModal'

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
function DatasetDetailsCard({ dataset, onRenamed, onDelete, onShowCompleteness, menuItems }) {
  return (
    <Card className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold text-gray-800">{dataset.name}</h1>
        <div className="shrink-0">
          <DatasetMenu dataset={dataset} onRenamed={onRenamed} onDelete={onDelete} extraItems={menuItems} />
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
// Scores only ever appear on the Evaluate Papers / Results side; a
// paper on this page is always shown exactly as retrieved, with no score.
export default function DatasetDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const providers = useConfiguredProviders()
  const [dataset, setDataset] = useState(null)
  const [error, setError] = useState(null)
  const [toggleError, setToggleError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_PAPER_FILTER)
  const [sort, setSort] = useState(DEFAULT_PAPER_SORT)
  // null until an abstract lookup has run on this dataset.
  const [lookup, setLookup] = useState(null)
  const autoLookupRef = useRef(null)
  // A check for new papers: which dataset one is running for (it can outlast the user's
  // stay on this page, which is reused when they open another dataset), and what it said.
  const [refreshingId, setRefreshingId] = useState(null)
  const viewedIdRef = useRef(id)
  const [refreshError, setRefreshError] = useState(null)
  const [refreshedNotice, setRefreshedNotice] = useState(null)
  // The Search completeness dialog (the numbers behind the summary on the details card).
  const [showCompleteness, setShowCompleteness] = useState(false)
  const loadedId = dataset?.id

  // Looks up missing abstracts. The lookup itself runs in lib/findAbstracts so
  // it keeps going if the user leaves this page; the subscription below fills
  // papers in as results come back. Papers a lookup already completed for are
  // left out by the server, so this only does new work. Used by both the
  // automatic run on opening a dataset and the button.
  const runLookup = useCallback((datasetId) => startLookup(datasetId), [])

  // Follows this dataset's lookup, including one started before the user left
  // and came back, which is replayed from the lookup's accumulated results.
  useEffect(() => {
    if (loadedId == null) return
    let active = true
    const sync = (state) => {
      if (!active) return
      const filledById = new Map(state.filledPapers.map((p) => [p.id, p]))
      const checkedIds = new Set(state.checkedIds)
      if (filledById.size || checkedIds.size) {
        // Only touch the dataset this lookup belongs to; the page may already
        // be loading a different one.
        setDataset((prev) =>
          prev?.id !== loadedId
            ? prev
            : {
                ...prev,
                papers: prev.papers.map((p) => {
                  if (filledById.has(p.id)) return { ...p, ...filledById.get(p.id) }
                  if (checkedIds.has(p.id)) return { ...p, abstract_checked: true }
                  return p
                }),
              }
        )
      }
      // A run that ended with nothing to try stays silent.
      setLookup(!state.running && state.attempted === 0 && !state.error ? null : state)
    }
    const current = getLookup(loadedId)
    if (current) sync(current)
    const unsubscribe = subscribeLookup(loadedId, sync)
    return () => {
      active = false
      unsubscribe()
    }
  }, [loadedId])

  useEffect(() => {
    viewedIdRef.current = id
  }, [id])

  useEffect(() => {
    let cancelled = false
    setError(null)
    setToggleError(null)
    setRefreshError(null)
    setRefreshedNotice(null)
    setShowCompleteness(false)
    setFilter(EMPTY_PAPER_FILTER)
    setLookup(null)
    setDataset(null)
    fetchJson(`/api/datasets/${id}`)
      .then((d) => !cancelled && setDataset(d))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
    }
  }, [id])

  // Start looking up missing abstracts once, when a dataset first loads (a
  // lookup already running for it is left alone).
  useEffect(() => {
    if (!dataset || autoLookupRef.current === dataset.id) return
    autoLookupRef.current = dataset.id
    if (dataset.papers.some(isLookupCandidate)) runLookup(dataset.id)
  }, [dataset, runLookup])

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

  // Searches the dataset's sources again for papers that appeared since it was last
  // searched and adds only those (no AI cost). The new ones are marked, and their
  // missing abstracts are looked up like any others.
  const checkForNewPapers = async () => {
    const startedFor = dataset.id
    // The page is reused when the user opens another dataset, so what comes back is
    // applied only while they are still looking at the dataset it was asked for. (The
    // server saves the new papers either way; opening that dataset again shows them.)
    const stillHere = () => String(viewedIdRef.current) === String(startedFor)
    setRefreshingId(startedFor)
    setRefreshError(null)
    setRefreshedNotice(null)
    try {
      const { new_count: newCount, dataset: updated } = await postJson(`/api/datasets/${startedFor}/refresh`, {})
      if (stillHere()) {
        setDataset(updated)
        setRefreshedNotice(newCount)
      }
      // Missing abstracts are looked up in the background, whichever page they are on.
      if (updated.papers.some(isLookupCandidate)) runLookup(updated.id)
    } catch (err) {
      if (stillHere()) setRefreshError(err.message)
    } finally {
      setRefreshingId((current) => (current === startedFor ? null : current))
    }
  }

  // The publishers whose abstracts need an API key that isn't saved yet.
  const keylessPublishers = PUBLISHER_LOOKUPS.filter((p) => !providers?.[p.key]).map((p) => p.label)

  const missingAbstracts = dataset.papers.filter(isMissingAbstract).length
  // Papers a lookup can still try, vs ones every source was already asked about.
  const lookupCandidates = dataset.papers.filter(isLookupCandidate).length
  const unfindable = missingAbstracts - lookupCandidates

  const includedCount = dataset.papers.filter((p) => !p.excluded).length
  const excludedCount = dataset.papers.length - includedCount
  const visiblePapers = sortPapers(filterPapers(dataset.papers, filter), sort)
  // The export holds the included papers only (an excluded one can be shown on this page).
  const exportItems = includedCount
    ? exportMenuItems({
        url: `/api/datasets/${dataset.id}/export`,
        all: dataset.papers.filter((p) => !p.excluded).map((p) => p.id),
        shown: visiblePapers.filter((p) => !p.excluded).map((p) => p.id),
        filterActive: isPaperFilterActive(filter),
        onError: setToggleError,
      })
    : []

  const refreshing = refreshingId === dataset.id

  // How the latest check for new papers went, if it stopped short of some papers.
  const lastCheck = summarizeRetrieval(dataset.last_refresh?.retrieval)
  const incompleteCheck = lastCheck && !lastCheck.complete ? lastCheck : null

  const yearRange = formatYearRange(dataset.oldest_year, dataset.newest_year, dataset.newest_publication_date)

  // The abstract lookup panel is hidden once every included paper with a DOI
  // has an abstract (and nothing is running).
  const showLookupPanel = missingAbstracts > 0 || Boolean(lookup?.running)

  return (
    <PageShell>
      <BackLink to="/datasets">Back to Paper Datasets</BackLink>

      <div className="relative mt-4">
        <DatasetDetailsCard
          dataset={dataset}
          onRenamed={(name) => setDataset((prev) => ({ ...prev, name }))}
          onDelete={async () => {
            await deleteJson(`/api/datasets/${dataset.id}`)
            navigate('/datasets')
          }}
          onShowCompleteness={() => setShowCompleteness(true)}
          menuItems={exportItems}
        />

        <div className="mt-6 flex items-center justify-between gap-4">
          <p className="text-sm text-gray-500">
            {includedCount} paper{includedCount === 1 ? '' : 's'}
            {excludedCount ? ` (${excludedCount} excluded)` : ''}
            {yearRange ? ` · ${yearRange}` : ''}
          </p>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={checkForNewPapers}
              disabled={refreshing}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              Check for new papers
            </button>
            <button
              type="button"
              onClick={() => navigate(`/evaluate?dataset=${dataset.id}`)}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
            >
              Evaluate Dataset
            </button>
          </div>
        </div>

        {refreshing ? (
          <div className="mt-3">
            <StageIndicator label="Checking the paper sources for new papers…" />
          </div>
        ) : null}
        {refreshError ? <p className="mt-3 text-sm text-red-600 dark:text-red-400">{refreshError}</p> : null}
        {refreshedNotice !== null && !refreshing ? (
          <p className="mt-3 text-sm text-gray-700">
            {refreshedNotice === 0
              ? 'No new papers found.'
              : `Found ${refreshedNotice} new paper${refreshedNotice === 1 ? '' : 's'}, marked New below.`}
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
              {lookup?.running ? (
                <>
                  <div className="flex items-center gap-2 text-sm text-gray-700">
                    <Spinner />
                    <span>
                      {lookup.total === null
                        ? 'Looking up abstracts…'
                        : `Looking up abstracts… ${lookup.attempted} of ${lookup.total}`}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-gray-700">It is safe to leave this page.</p>
                </>
              ) : lookupCandidates > 0 ? (
                <button
                  type="button"
                  onClick={() => runLookup(dataset.id)}
                  className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
                >
                  Find missing abstracts ({lookupCandidates})
                </button>
              ) : null}

              {lookup && !lookup.running && !lookup.error ? (
                <p className="mt-3 text-sm text-gray-700">
                  {lookup.filledCount > 0
                    ? `Found ${lookup.filledCount} abstract${lookup.filledCount === 1 ? '' : 's'}.`
                    : 'No new abstracts found.'}
                </p>
              ) : null}
              {!lookup?.running && unfindable > 0 ? (
                <p className="mt-2 text-sm text-gray-700">
                  {unfindable} paper{unfindable === 1 ? ' has' : 's have'} no abstract in any source checked.
                </p>
              ) : null}
              {lookup?.noDoi > 0 ? (
                <p className="mt-2 text-xs text-gray-500">
                  {lookup.noDoi} other paper{lookup.noDoi === 1 ? ' has' : 's have'} no DOI, so can’t be looked up.
                </p>
              ) : null}
              {Object.entries(lookup?.sourceErrors ?? {}).map(([source, message]) => (
                <p key={source} className="mt-2 text-xs text-amber-700 dark:text-amber-400">
                  {message}
                </p>
              ))}
              {lookup?.error ? <p className="mt-2 text-sm text-red-600 dark:text-red-400">{lookup.error}</p> : null}

              <p className="mt-3 text-xs text-gray-400">
                {!providers ? (
                  'Missing abstracts are looked up automatically.'
                ) : keylessPublishers.length === 0 ? (
                  'The remaining papers without abstracts require manual updating. You can open the paper DOI link and copy the abstract into the paper entry on this page.'
                ) : (
                  <>
                    Missing abstracts are looked up automatically. Add {keylessPublishers.join(' and ')} API{' '}
                    {keylessPublishers.length === 1 ? 'key' : 'keys'} in{' '}
                    <Link to="/settings/databases" className="underline">
                      Settings
                    </Link>{' '}
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
