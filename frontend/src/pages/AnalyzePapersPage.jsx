import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import { StageIndicator } from '../components/Spinner'
import AiModelSelect, { hasConfiguredProvider, defaultAiChoice } from '../components/AiModelSelect'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import { postJson } from '../lib/api'
import { driveAnalysisRun } from '../lib/driveAnalysisRun'

export default function AnalyzePapersPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const preselectedId = searchParams.get('dataset')
  const providers = useConfiguredProviders()
  const [datasets, setDatasets] = useState(null)
  const [selected, setSelected] = useState(() => new Set(preselectedId ? [Number(preselectedId)] : []))
  // Deliberately never prefilled from a dataset's discovery question - this
  // is where the user is meant to stop and think precisely about what
  // they're actually looking for, which can (and often should) differ from
  // whatever question retrieved the dataset in the first place.
  const [gradingPrompt, setGradingPrompt] = useState('')
  const [aiChoice, setAiChoice] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(null)
  // Aborts a prior in-flight submission before starting a new one - guards
  // against a rapid double-submit (double-click, double Enter) firing two
  // real analysis runs (and paying for LLM scoring twice) before the
  // submit button's disabled state has re-rendered.
  const activeRequestRef = useRef(null)

  useEffect(() => {
    fetch('/api/datasets')
      .then((res) => res.json())
      .then((data) => setDatasets(data.datasets ?? []))
      .catch((err) => setError(err.message))
  }, [])

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const configured = hasConfiguredProvider(providers)
  const choice = aiChoice || defaultAiChoice(providers)

  const runAnalysis = async (e) => {
    e.preventDefault()
    if (!configured) {
      navigate('/settings')
      return
    }
    if (!selected.size || !gradingPrompt.trim()) return

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setStatus('loading')
    setError(null)
    setProgress(null)

    try {
      const run = await postJson(
        '/api/analysis-runs',
        {
          dataset_ids: [...selected],
          grading_prompt: gradingPrompt.trim(),
          ai_api: choice.ai_api,
          ai_model: choice.ai_model,
        },
        { signal: controller.signal }
      )
      await driveAnalysisRun(run.id, controller.signal, (update) => {
        setProgress({ processed: update.results.length, remaining: update.remaining })
      })
      navigate(`/results/${run.id}`)
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <PageShell title="Analyze Papers">
      <Card>
        <form onSubmit={runAnalysis} className="flex flex-col gap-4">
          <div>
            <span className="block text-sm font-medium text-gray-700">Datasets to analyze</span>
            <div className="mt-1 flex flex-col gap-1 max-h-64 overflow-auto">
              {(datasets ?? []).map((d) => (
                <label key={d.id} className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={selected.has(d.id)}
                    onChange={() => toggle(d.id)}
                    className="rounded"
                  />
                  {d.verbose_query}
                  <span className="text-gray-400">({d.paper_count})</span>
                </label>
              ))}
              {datasets && datasets.length === 0 ? (
                <p className="text-sm text-gray-500">No datasets yet - create one from Discover Papers.</p>
              ) : null}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700">Research question</label>
            <textarea
              value={gradingPrompt}
              onChange={(e) => setGradingPrompt(e.target.value)}
              placeholder="Precisely what are you looking for in this literature review?"
              rows={3}
              className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">AI model</span>
            <div className="mt-1">
              {configured ? (
                <AiModelSelect providers={providers} value={choice} onChange={setAiChoice} />
              ) : (
                <p className="text-sm text-gray-400">No API key configured yet.</p>
              )}
            </div>
          </div>

          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          {status === 'loading' ? (
            <StageIndicator
              label={
                progress
                  ? `Scoring papers… ${progress.processed} done, ${progress.remaining} remaining`
                  : 'Scoring papers…'
              }
            />
          ) : null}

          <button
            type="submit"
            disabled={status === 'loading' || (configured && (!selected.size || !gradingPrompt.trim()))}
            className="self-start rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {!configured ? 'Configure API key' : status === 'loading' ? 'Analyzing…' : 'Run Analysis'}
          </button>
        </form>
      </Card>
    </PageShell>
  )
}
