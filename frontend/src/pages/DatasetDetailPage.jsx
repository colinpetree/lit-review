import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { PageShell, Card, BackLink } from '../components/ui'
import Spinner from '../components/Spinner'
import PaperCard from '../components/PaperCard'
import PaperFilterBar from '../components/PaperFilterBar'
import { EMPTY_PAPER_FILTER, filterPapers, isPaperFilterActive } from '../lib/paperFilter'
import EditableCardHeader from '../components/EditableCardHeader'
import useSavedState from '../lib/useSavedState'
import useUnsavedChangesWarning from '../lib/useUnsavedChangesWarning'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import { fetchJson, patchJson } from '../lib/api'
import { driveFindAbstracts } from '../lib/findAbstracts'
import { sourceLabel } from '../lib/paperSources'
import { formatDateTime, formatYearRange } from '../lib/format'

// The data set's short title (editable) and the topic it was retrieved with
// (fixed), in the same preview/Edit/Save card style as the Settings page.
function DatasetDetailsCard({ dataset, onSaved }) {
  const [name, setName] = useState(dataset.name)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  const isDirty = Boolean(name.trim()) && name.trim() !== dataset.name
  useUnsavedChangesWarning(editing && isDirty)

  function startEditing() {
    setName(dataset.name)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  function save() {
    commit(async () => {
      const updated = await patchJson(`/api/datasets/${dataset.id}`, { name: name.trim() })
      onSaved(updated)
    })
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="Data set details"
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={isDirty}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={save}
      />

      <div className="flex flex-col gap-1.5">
        {editing ? (
          <>
            <label className="text-sm font-medium text-gray-700">Data set title</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={saving}
              maxLength={120}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900"
            />
          </>
        ) : (
          <>
            <p className="text-sm font-medium text-gray-700">Data set title</p>
            <p className="text-sm text-gray-900">{dataset.name}</p>
          </>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Topic</p>
        <p className="whitespace-pre-wrap text-sm text-gray-900">{dataset.verbose_query}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Paper sources</p>
        <p className="text-sm text-gray-900">{dataset.sources.map(sourceLabel).join(', ')}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Created</p>
        <p className="text-sm text-gray-900">{formatDateTime(dataset.created_at)}</p>
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}
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
// Scores only ever appear on the Analyze Papers / Past Results side; a
// paper on this page is always shown exactly as retrieved, with no score.
export default function DatasetDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const providers = useConfiguredProviders()
  const [dataset, setDataset] = useState(null)
  const [error, setError] = useState(null)
  const [toggleError, setToggleError] = useState(null)
  const [filter, setFilter] = useState(EMPTY_PAPER_FILTER)
  // null until an abstract lookup has run on this data set.
  const [lookup, setLookup] = useState(null)
  const lookupRequestRef = useRef(null)
  const autoLookupRef = useRef(null)

  // Looks up missing abstracts, filling papers in as they come back. Papers a
  // lookup already completed for are left out by the server, so this only does
  // new work. Used by both the automatic run on opening a data set and the
  // button.
  const runLookup = useCallback(async (datasetId) => {
    lookupRequestRef.current?.abort()
    const controller = new AbortController()
    lookupRequestRef.current = controller

    setLookup({ running: true, total: null, attempted: 0, filledCount: 0, sourceErrors: {}, noDoi: 0 })
    try {
      const result = await driveFindAbstracts(datasetId, controller.signal, (progress) => {
        if (controller.signal.aborted) return
        const filledById = new Map(progress.filled.map((p) => [p.id, p]))
        const checkedIds = new Set(progress.checked)
        if (filledById.size || checkedIds.size) {
          setDataset((prev) => ({
            ...prev,
            papers: prev.papers.map((p) => {
              if (filledById.has(p.id)) return { ...p, ...filledById.get(p.id) }
              if (checkedIds.has(p.id)) return { ...p, abstract_checked: true }
              return p
            }),
          }))
        }
        setLookup((prev) => ({ ...prev, ...progress, running: true }))
      })
      if (controller.signal.aborted) return
      // An automatic run with nothing to try stays silent.
      if (result.attempted === 0) setLookup(null)
      else setLookup((prev) => ({ ...prev, ...result, running: false }))
    } catch (err) {
      if (err.name === 'AbortError') return
      setLookup((prev) => ({ ...prev, running: false, error: err.message }))
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    lookupRequestRef.current?.abort()
    setError(null)
    setToggleError(null)
    setFilter(EMPTY_PAPER_FILTER)
    setLookup(null)
    setDataset(null)
    fetchJson(`/api/datasets/${id}`)
      .then((d) => !cancelled && setDataset(d))
      .catch((err) => !cancelled && setError(err.message))
    return () => {
      cancelled = true
      lookupRequestRef.current?.abort()
    }
  }, [id])

  // Start looking up missing abstracts once, when a data set first loads.
  useEffect(() => {
    if (!dataset || autoLookupRef.current === dataset.id) return
    autoLookupRef.current = dataset.id
    if (dataset.papers.some(isLookupCandidate)) runLookup(dataset.id)
  }, [dataset, runLookup])

  if (error) {
    return (
      <PageShell title="Paper Data Set">
        <p className="text-sm text-red-600">{error}</p>
      </PageShell>
    )
  }
  if (!dataset) {
    return (
      <PageShell title="Paper Data Set">
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

  // The publishers whose abstracts need an API key that isn't saved yet.
  const keylessPublishers = PUBLISHER_LOOKUPS.filter((p) => !providers?.[p.key]).map((p) => p.label)

  const missingAbstracts = dataset.papers.filter(isMissingAbstract).length
  // Papers a lookup can still try, vs ones every source was already asked about.
  const lookupCandidates = dataset.papers.filter(isLookupCandidate).length
  const unfindable = missingAbstracts - lookupCandidates

  const includedCount = dataset.papers.filter((p) => !p.excluded).length
  const excludedCount = dataset.papers.length - includedCount
  const visiblePapers = filterPapers(dataset.papers, filter)

  const yearRange = formatYearRange(dataset.oldest_year, dataset.newest_year, dataset.newest_publication_date)

  // The abstract lookup panel is hidden once every included paper with a DOI
  // has an abstract (and nothing is running).
  const showLookupPanel = missingAbstracts > 0 || Boolean(lookup?.running)

  return (
    <PageShell>
      <BackLink to="/datasets">Back to Paper Data Sets</BackLink>

      <div className="relative mt-4">
        <DatasetDetailsCard
          dataset={dataset}
          onSaved={(updated) => setDataset((prev) => ({ ...prev, name: updated.name }))}
        />

        <div className="mt-6 flex items-center justify-between gap-4">
          <p className="text-sm text-gray-500">
            {includedCount} paper{includedCount === 1 ? '' : 's'}
            {excludedCount ? ` (${excludedCount} excluded)` : ''}
            {yearRange ? ` · ${yearRange}` : ''}
            {dataset.cost ? ` · expansion cost: $${dataset.cost.toFixed(4)}` : ''}
          </p>
          <button
            type="button"
            onClick={() => navigate(`/analyze?dataset=${dataset.id}`)}
            className="shrink-0 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            Analyze Dataset
          </button>
        </div>

        {/* On a wide window this sits just outside the right edge of the
            content column and stays in view while the paper list scrolls, so
            the column never moves whether it is shown or not. The breakpoint is
            where the sidebar, the column and this panel all fit; on a narrower
            window it takes its place in the page, above the paper list. */}
        {showLookupPanel ? (
          <aside className="mt-6 min-[1560px]:absolute min-[1560px]:inset-y-0 min-[1560px]:left-full min-[1560px]:mt-0 min-[1560px]:ml-6 min-[1560px]:w-64">
            <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm min-[1560px]:sticky min-[1560px]:top-6">
              <h2 className="mb-3 text-lg font-semibold text-gray-900">Missing Abstracts</h2>
              {lookup?.running ? (
                <div className="flex items-center gap-2 text-sm text-gray-700">
                  <Spinner />
                  <span>
                    {lookup.total === null
                      ? 'Looking up abstracts…'
                      : `Looking up abstracts… ${lookup.attempted} of ${lookup.total}`}
                  </span>
                </div>
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
                <p key={source} className="mt-2 text-xs text-amber-700">
                  {message}
                </p>
              ))}
              {lookup?.error ? <p className="mt-2 text-sm text-red-600">{lookup.error}</p> : null}

              <p className="mt-3 text-xs text-gray-400">
                {!providers ? (
                  'Missing abstracts are looked up automatically.'
                ) : keylessPublishers.length === 0 ? (
                  'The remaining papers without abstracts require manual updating. You can open the paper DOI link and copy the abstract into the paper entry on this page.'
                ) : (
                  <>
                    Missing abstracts are looked up automatically. Add {keylessPublishers.join(' and ')} API{' '}
                    {keylessPublishers.length === 1 ? 'key' : 'keys'} in{' '}
                    <Link to="/settings" className="underline">
                      Settings
                    </Link>{' '}
                    to find more, or you can update them manually.
                  </>
                )}
              </p>
            </div>
          </aside>
        ) : null}

        {toggleError ? <p className="mt-3 text-sm text-red-600">{toggleError}</p> : null}

        <PaperFilterBar
          filter={filter}
          onChange={setFilter}
          shown={visiblePapers.length}
          total={dataset.papers.length}
        />

        {isPaperFilterActive(filter) && visiblePapers.length === 0 ? (
          <p className="mt-4 text-sm text-gray-500">No papers match the current filters.</p>
        ) : null}

        <ul className="mt-4 flex flex-col gap-3">
          {visiblePapers.map((paper, index) => (
            <PaperCard
              key={paper.id ?? `${paper.doi ?? paper.title}-${index}`}
              result={paper}
              onUpdate={handlePaperUpdate}
              onToggleExclude={toggleExclude}
            />
          ))}
        </ul>
      </div>
    </PageShell>
  )
}
