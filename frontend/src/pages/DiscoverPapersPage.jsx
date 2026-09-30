import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import { StageIndicator } from '../components/Spinner'
import AiModelSelect, { hasConfiguredProvider, defaultAiChoice } from '../components/AiModelSelect'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import { postJson } from '../lib/api'

// Discover Papers only retrieves papers into a dataset - it never scores or
// analyzes them. Relevance scoring is a separate, deliberate step the user
// takes on the Analyze Papers page (against whatever grading criteria they
// choose there, which may differ from this retrieval question) - a dataset
// fresh out of Discover Papers should show no scores at all.
const STAGE_LABELS = {
  query: 'Processing query…',
  retrieval: 'Submitting to Paper Databases…',
}

const SOURCES = [
  { id: 'openalex', label: 'OpenAlex', enabled: true },
  { id: 'pubmed', label: 'PubMed (coming soon)', enabled: false },
  { id: 'semantic_scholar', label: 'Semantic Scholar (coming soon)', enabled: false },
]

export default function DiscoverPapersPage() {
  const navigate = useNavigate()
  const providers = useConfiguredProviders()
  const [question, setQuestion] = useState('')
  const [fromYear, setFromYear] = useState('')
  const [toYear, setToYear] = useState('')
  const [aiChoice, setAiChoice] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)
  const [stage, setStage] = useState(null) // 'query' | 'retrieval'
  // Set only when the OpenAlex retrieval step specifically fails - holds
  // everything needed to retry *just* that step (already-expanded queries +
  // their usage) without paying for another LLM expansion call.
  const [pendingRetrieval, setPendingRetrieval] = useState(null)
  const activeRequestRef = useRef(null)

  const configured = hasConfiguredProvider(providers)
  const choice = aiChoice || defaultAiChoice(providers)

  const runDiscovery = async (e) => {
    e.preventDefault()
    if (!configured) {
      navigate('/settings')
      return
    }
    const trimmed = question.trim()
    if (!trimmed) return

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
          ai_model: choice.ai_model,
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
        usage: expand.usage,
        from_year: fromYear ? Number(fromYear) : undefined,
        to_year: toYear ? Number(toYear) : undefined,
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
    if (!pendingRetrieval) return

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setStatus('loading')
    setError(null)
    setStage('retrieval')

    try {
      const dataset = await postJson('/api/datasets', pendingRetrieval, { signal: controller.signal })
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
    <PageShell title="Discover Papers">
      <Card>
        <form onSubmit={runDiscovery} className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">Topic</label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. nitrogen cycling in peatland soils"
              rows={3}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="flex gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">From year</label>
              <input
                type="number"
                value={fromYear}
                onChange={(e) => setFromYear(e.target.value)}
                className="mt-1 w-28 rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">To year</label>
              <input
                type="number"
                value={toYear}
                onChange={(e) => setToYear(e.target.value)}
                className="mt-1 w-28 rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">Paper sources</span>
            <div className="mt-1 flex flex-col gap-1">
              {SOURCES.map((source) => (
                <label
                  key={source.id}
                  className={`flex items-center gap-2 text-sm ${source.enabled ? 'text-gray-700' : 'text-gray-400'}`}
                >
                  <input type="checkbox" checked={source.enabled} disabled className="rounded" />
                  {source.label}
                </label>
              ))}
            </div>
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">AI model (for query expansion)</span>
            <div className="mt-1">
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
            disabled={status === 'loading' || (configured && !question.trim())}
            className="self-start rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
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
