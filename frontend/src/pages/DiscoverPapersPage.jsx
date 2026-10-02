import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import { StageIndicator } from '../components/Spinner'
import AiModelSelect, { hasConfiguredProvider, defaultAiChoice } from '../components/AiModelSelect'
import AutoGrowTextarea from '../components/AutoGrowTextarea'
import Checkbox from '../components/Checkbox'
import DateRangeField from '../components/DateRangeField'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import { postJson } from '../lib/api'
import { DEFAULT_SOURCES, PAPER_SOURCES } from '../lib/paperSources'
import { PubMedIcon } from '../components/ProviderIcons'
import { MODELS_BY_PROVIDER } from '../lib/models'
import { loadDiscoverSettings, saveDiscoverSettings } from '../lib/discoverSettings'

// A source can be used when it needs no API key, or its key is saved.
const isSourceAvailable = (source, providers) => !source.key || Boolean(providers?.[source.key])

// Discover Papers only retrieves papers into a dataset - it never scores or
// analyzes them. Relevance scoring is a separate, deliberate step the user
// takes on the Analyze Papers page (against whatever grading criteria they
// choose there, which may differ from this retrieval question) - a dataset
// fresh out of Discover Papers should show no scores at all.
const STAGE_LABELS = {
  query: 'Processing query…',
  retrieval: 'Submitting to Paper Databases…',
}

export default function DiscoverPapersPage() {
  const navigate = useNavigate()
  const providers = useConfiguredProviders()
  // The sources and model start from the last run's (saved when a run starts),
  // so they stay that way until a run is made with different ones. Edits that
  // were never run are not kept. The topic and the year range always start blank.
  const [remembered] = useState(loadDiscoverSettings)
  const [question, setQuestion] = useState('')
  const [sources, setSources] = useState(remembered.sources?.length ? remembered.sources : DEFAULT_SOURCES)
  const [sourcesEdited, setSourcesEdited] = useState(false)
  const [fromYear, setFromYear] = useState('')
  const [toYear, setToYear] = useState('')
  const [aiChoice, setAiChoice] = useState(remembered.aiChoice)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)
  const [stage, setStage] = useState(null) // 'query' | 'retrieval'
  // Set only when the OpenAlex retrieval step specifically fails - holds
  // everything needed to retry *just* that step (already-expanded queries +
  // their usage) without paying for another LLM expansion call.
  const [pendingRetrieval, setPendingRetrieval] = useState(null)
  const activeRequestRef = useRef(null)

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
  // checkboxes themselves, none selected stays none (Discover Papers is then
  // disabled) instead of snapping back to the default.
  const usableSources = sources.filter((id) => {
    const source = PAPER_SOURCES.find((s) => s.id === id)
    return source && isSourceAvailable(source, providers)
  })
  const activeSources = usableSources.length || !providers || sourcesEdited ? usableSources : DEFAULT_SOURCES

  const runDiscovery = async (e) => {
    e.preventDefault()
    if (!configured) {
      navigate('/settings')
      return
    }
    const trimmed = question.trim()
    if (!trimmed || activeSources.length === 0) return

    saveDiscoverSettings({ sources: activeSources, aiChoice: choice })

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setStatus('loading')
    setError(null)
    setPendingRetrieval(null)
    setStage('query')

    try {
      const expand = await postJson(
        '/api/datasets/expand',
        {
          question: trimmed,
          from_year: fromYear ? Number(fromYear) : undefined,
          to_year: toYear ? Number(toYear) : undefined,
          ai_api: choice.ai_api,
          ai_model: choice.ai_model,
          sources: activeSources,
        },
        { signal: controller.signal }
      )

      if (expand.reused) {
        navigate(`/datasets/${expand.dataset.id}`)
        return
      }

      setStage('retrieval')
      const retrievalPayload = {
        question: trimmed,
        queries: expand.queries,
        title: expand.title,
        usage: expand.usage,
        from_year: fromYear ? Number(fromYear) : undefined,
        to_year: toYear ? Number(toYear) : undefined,
        sources: activeSources,
      }

      let dataset
      try {
        dataset = await postJson('/api/datasets', retrievalPayload, { signal: controller.signal })
      } catch (err) {
        if (err.name === 'AbortError') return
        setError(err.message)
        setStatus('error')
        setPendingRetrieval(retrievalPayload)
        return
      }

      navigate(`/datasets/${dataset.id}`)
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message)
      setStatus('error')
    } finally {
      setStage(null)
    }
  }

  const retryRetrieval = async () => {
    if (!pendingRetrieval || activeSources.length === 0) return

    saveDiscoverSettings({ sources: activeSources, aiChoice: choice })

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setStatus('loading')
    setError(null)
    setStage('retrieval')

    try {
      // Sent with the sources as they are checked now, so a source that keeps
      // failing can be unchecked before retrying.
      const dataset = await postJson(
        '/api/datasets',
        { ...pendingRetrieval, sources: activeSources },
        { signal: controller.signal }
      )
      setPendingRetrieval(null)
      navigate(`/datasets/${dataset.id}`)
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message)
      setStatus('error')
      // keep pendingRetrieval so the button stays available to try again
    } finally {
      setStage(null)
    }
  }

  return (
    <PageShell
      title="Discover Papers"
      description="Write a sentence describing the topic you want to find research papers about. Choose the databases you want to search and the AI model to process your sentence with. This will create a group of papers associated with your search."
    >
      <Card>
        <form onSubmit={runDiscovery} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Research paper dataset topic</label>
            <AutoGrowTextarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. nitrogen cycling in peatland soils"
              rows={3}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">Publication dates</span>
            <DateRangeField
              fromYear={fromYear}
              toYear={toYear}
              onFromChange={setFromYear}
              onToChange={setToYear}
              disabled={status === 'loading'}
            />
          </div>

          <div>
            <span className="block select-none text-sm font-medium text-gray-700">Paper sources</span>
            <div className="mt-1 flex flex-col gap-1">
              {PAPER_SOURCES.filter((source) => !source.hiddenWithoutKey || providers?.[source.key]).map((source) => {
                // A source that needs an API key can't be chosen until one is saved.
                const needsKey = source.key && !providers?.[source.key]
                return (
                  <Checkbox
                    key={source.id}
                    checked={activeSources.includes(source.id)}
                    disabled={needsKey || status === 'loading'}
                    onChange={(checked) => {
                      setSourcesEdited(true)
                      setSources(
                        checked ? [...activeSources, source.id] : activeSources.filter((id) => id !== source.id)
                      )
                    }}
                  >
                    <source.icon size={14} className="shrink-0" />
                    <span>
                      {source.label}
                      {needsKey ? (
                        <span className="ml-1 text-xs">
                          (needs an API key in{' '}
                          <Link to="/settings" className="underline">
                            Settings
                          </Link>
                          )
                        </span>
                      ) : null}
                    </span>
                  </Checkbox>
                )
              })}
              <Checkbox checked={false} disabled>
                <PubMedIcon size={14} className="shrink-0" />
                PubMed (coming soon)
              </Checkbox>
            </div>
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

          {status === 'loading' ? <StageIndicator label={STAGE_LABELS[stage]} /> : null}

          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          {pendingRetrieval ? (
            <button
              type="button"
              onClick={retryRetrieval}
              disabled={status === 'loading'}
              className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
            >
              Retry fetching papers
            </button>
          ) : null}

          <button
            type="submit"
            disabled={status === 'loading' || (configured && (!question.trim() || activeSources.length === 0))}
            // White while it can't be run yet (no topic or source), blue once it can.
            // While a search is running it stays blue, just faded.
            className={`self-start rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
              status === 'loading'
                ? 'border-blue-600 bg-blue-600 text-white opacity-50'
                : 'border-blue-600 bg-blue-600 text-white hover:border-blue-700 hover:bg-blue-700 disabled:border-gray-200 disabled:bg-white disabled:text-gray-400 disabled:hover:bg-white'
            }`}
          >
            {!configured
              ? 'Configure API key'
              : status === 'loading'
                ? 'Working…'
                : 'Discover Papers'}
          </button>
        </form>
      </Card>
    </PageShell>
  )
}
