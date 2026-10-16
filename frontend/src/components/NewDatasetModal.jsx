import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSettingsModal } from './SettingsModalProvider'
import Modal from './Modal'
import ConfirmModal from './ConfirmModal'
import { useJobs } from './JobsProvider'
import AiModelSelect, { hasConfiguredProvider, defaultAiChoice } from './AiModelSelect'
import AutoGrowTextarea from './AutoGrowTextarea'
import Checkbox from './Checkbox'
import DateRangeField from './DateRangeField'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import { getPubMedEnabled } from '../lib/pubmedSetting'
import { DEFAULT_SOURCES, PAPER_SOURCES } from '../lib/paperSources'
import { MODELS_BY_PROVIDER } from '../lib/models'
import { loadDiscoverSettings, saveDiscoverSettings } from '../lib/discoverSettings'
import { SEARCH_LIMIT_OPTIONS, normalizeSearchLimit } from '../lib/searchLimit'
import Combobox from './Combobox'
import { dateBounds, dateRangeError } from '../lib/dateRange'

// A source is offered (and used) only when it is enabled: it needs no API key or
// its key is saved, and PubMed has not been switched off in Settings.
const isSourceAvailable = (source, providers, pubmedEnabled) =>
  (source.id !== 'pubmed' || pubmedEnabled) && (!source.key || Boolean(providers?.[source.key]))

// New Dataset only retrieves papers into a dataset - it never grades or
// evaluates them. Relevance grading is a separate, deliberate step the user
// takes with New Evaluation (against whatever grading criteria they
// choose there, which may differ from this retrieval question) - a dataset
// fresh out of a search should show no grades at all.

export default function NewDatasetModal({ onClose }) {
  const navigate = useNavigate()
  const providers = useConfiguredProviders()
  // Read on every render, not once: the switch in Settings can change while this page stays open,
  // and closing Settings re-renders this page (its context value changes).
  const { openSettings } = useSettingsModal()
  const pubmedEnabled = getPubMedEnabled()
  // The sources and model start from the last run's (saved when a run starts),
  // so they stay that way until a run is made with different ones. Edits that
  // were never run are not kept. The topic and the year range always start blank.
  const [remembered] = useState(loadDiscoverSettings)
  const [question, setQuestion] = useState('')
  const [sources, setSources] = useState(remembered.sources?.length ? remembered.sources : DEFAULT_SOURCES)
  const [sourcesEdited, setSourcesEdited] = useState(false)
  // How many of the most relevant papers each search keeps (per query and source).
  const [searchLimit, setSearchLimit] = useState(() => normalizeSearchLimit(remembered.searchLimit))
  // Each end of the publication dates is typed as a year or a full date.
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [aiChoice, setAiChoice] = useState(remembered.aiChoice)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)
  const { startJob } = useJobs()

  // Only the moment of handing the search over is spent here: the search itself runs in the
  // background and shows up on the Paper Datasets list.
  const loading = status === 'loading'
  const dirty = Boolean(question.trim() || fromDate || toDate)
  // Closing with a typed topic asks first, so nothing typed is thrown away by accident.
  const requestClose = () => (dirty && !loading ? setConfirmingDiscard(true) : onClose())

  const configured = hasConfiguredProvider(providers)
  // A remembered model that's no longer listed or configured falls back to the default.
  const choiceUsable =
    aiChoice &&
    providers?.[aiChoice.ai_api] &&
    MODELS_BY_PROVIDER[aiChoice.ai_api]?.some((m) => m.id === aiChoice.ai_model)
  const choice = choiceUsable ? aiChoice : defaultAiChoice(providers)

  // The selected sources that can actually be used right now: a remembered one
  // whose key has since been removed (or which no longer exists) is dropped,
  // and if that leaves none the default is used. Once the user has changed the
  // checkboxes themselves, none selected stays none (the search is then
  // disabled) instead of snapping back to the default.
  const usableSources = sources.filter((id) => {
    const source = PAPER_SOURCES.find((s) => s.id === id)
    return source && isSourceAvailable(source, providers, pubmedEnabled)
  })
  const activeSources = usableSources.length || !providers || sourcesEdited ? usableSources : DEFAULT_SOURCES

  const runDiscovery = async (e) => {
    e.preventDefault()
    if (!configured) {
      openSettings('ai')
      return
    }
    const trimmed = question.trim()
    if (!trimmed || activeSources.length === 0) return

    const rangeError = dateRangeError(fromDate, toDate)
    if (rangeError) {
      setError(rangeError)
      setStatus('error')
      return
    }
    const { from, to } = dateBounds(fromDate, toDate)

    saveDiscoverSettings({ sources: activeSources, searchLimit, aiChoice: choice })

    setStatus('loading')
    setError(null)
    try {
      const result = await startJob({
        kind: 'dataset_search',
        question: trimmed,
        from_date: from ?? undefined,
        to_date: to ?? undefined,
        ai_api: choice.ai_api,
        ai_model: choice.ai_model,
        sources: activeSources,
        search_limit: searchLimit,
      })
      // The same search was already done: open that dataset instead of searching again.
      if (result.reused) navigate(`/datasets/${result.dataset.id}`)
      onClose()
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <Modal title="New Dataset" onClose={requestClose} busy={loading} closeOnBackdrop={false} closeOnEscape={false} wide scroll>
      <p className="mt-2 text-sm text-gray-600">
        Write a sentence describing the topic you want to find research papers about. Choose the databases you want to search and the AI model to process your sentence with. This will create a dataset of papers with abstracts associated with your search.
      </p>
      <div className="mt-4">
        <form onSubmit={runDiscovery} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Research paper dataset topic</label>
            <AutoGrowTextarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Describe the topic in a sentence or two"
              maxLength={4000}
              rows={3}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">Publication dates</span>
            <DateRangeField
              fromDate={fromDate}
              toDate={toDate}
              onFromChange={setFromDate}
              onToChange={setToDate}
              disabled={status === 'loading'}
            />
          </div>

          <div>
            <span className="block select-none text-sm font-medium text-gray-700">Paper sources</span>
            <div className="mt-1 flex flex-col gap-1">
              {PAPER_SOURCES.filter((source) => isSourceAvailable(source, providers, pubmedEnabled)).map((source) => (
                <Checkbox
                  key={source.id}
                  checked={activeSources.includes(source.id)}
                  disabled={status === 'loading'}
                  // Only the box and the name toggle it, not the rest of the row.
                  className="self-start"
                  onChange={(checked) => {
                    setSourcesEdited(true)
                    setSources(
                      checked ? [...activeSources, source.id] : activeSources.filter((id) => id !== source.id)
                    )
                  }}
                >
                  <source.icon size={14} className="shrink-0" />
                  {source.label}
                </Checkbox>
              ))}
            </div>
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">Papers kept per search</span>
            <div className="mt-1 max-w-xs">
              <Combobox
                options={SEARCH_LIMIT_OPTIONS}
                value={searchLimit}
                onChange={setSearchLimit}
                placeholder="Papers kept per search"
                searchable={false}
              />
            </div>
            <p className="mt-1 text-xs text-gray-400">
              Each search keeps this many of the most relevant papers from each source. Keep the topic narrow:
              you can combine several datasets when you evaluate.
            </p>
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">AI model</span>
            <div className="mt-1 max-w-xs">
              {configured ? (
                <AiModelSelect providers={providers} value={choice} onChange={setAiChoice} />
              ) : (
                <p className="text-sm text-gray-400">No API key configured yet.</p>
              )}
            </div>
          </div>

          {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}

          <button
            type="submit"
            disabled={!providers || status === 'loading' || (configured && (!question.trim() || activeSources.length === 0))}
            // White while it can't be run yet (key status still loading, no topic
            // or source), blue once it can. While it is being handed over it stays
            // blue, just faded.
            className={`self-start rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
              status === 'loading'
                ? 'border-blue-600 bg-blue-600 text-white opacity-50'
                : 'border-blue-600 bg-blue-600 text-white hover:border-blue-700 hover:bg-blue-700 disabled:border-gray-200 disabled:bg-surface disabled:text-gray-400 disabled:hover:bg-surface'
            }`}
          >
            {providers && !configured
              ? 'Configure API key'
              : status === 'loading'
                ? 'Starting…'
                : 'Search for Papers'}
          </button>
          <p className="text-xs text-gray-400">
            The search runs in the background. You can close this window and keep using Lit Review; the dataset
            appears in the list and shows when it is done.
          </p>
        </form>
      </div>
      {confirmingDiscard ? (
        <ConfirmModal
          title="Discard this search?"
          message="What you typed will be lost."
          confirmLabel="Discard"
          danger
          onConfirm={() => onClose()}
          onClose={() => setConfirmingDiscard(false)}
        />
      ) : null}
    </Modal>
  )
}
