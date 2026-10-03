import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { X } from 'lucide-react'
import Combobox from '../components/Combobox'
import { PageShell, Card } from '../components/ui'
import { navIcon } from '../lib/navItems'
import { StageIndicator } from '../components/Spinner'
import AiModelSelect, { hasConfiguredProvider, defaultAiChoice, usableAiChoice } from '../components/AiModelSelect'
import useConfiguredProviders from '../lib/useConfiguredProviders'
import PromptCombobox, { NEW_PROMPT } from '../components/PromptCombobox'
import AutoGrowTextarea from '../components/AutoGrowTextarea'
import { fetchJson, postJson } from '../lib/api'
import { driveAnalysisRun } from '../lib/driveAnalysisRun'
import { formatDateTime } from '../lib/format'
import { loadEvaluateAiChoice, saveEvaluateAiChoice } from '../lib/evaluateSettings'

export default function EvaluatePapersPage() {
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
  // NEW_PROMPT (write the ideal research paper contents below) or a saved prompt's id.
  const [promptChoice, setPromptChoice] = useState(NEW_PROMPT)
  const [prompts, setPrompts] = useState([])
  // Starts from the model of the last run (saved when a run starts); one that is
  // no longer listed or configured falls back to the default.
  const [aiChoice, setAiChoice] = useState(loadEvaluateAiChoice)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(null)
  // Aborts a prior in-flight submission before starting a new one - guards
  // against a rapid double-submit (double-click, double Enter) firing two
  // real analysis runs (and paying for LLM scoring twice) before the
  // submit button's disabled state has re-rendered.
  const activeRequestRef = useRef(null)

  useEffect(() => {
    fetchJson('/api/datasets')
      .then((data) => {
        const list = data.datasets ?? []
        setDatasets(list)
        // A ?dataset= link to a dataset that was deleted (or never existed)
        // must not stay selected, or Run would be enabled with no badge.
        const ids = new Set(list.map((d) => d.id))
        setSelected((prev) => new Set([...prev].filter((id) => ids.has(id))))
      })
      .catch((err) => setError(err.message))
    fetchJson('/api/prompts')
      .then((data) => setPrompts(data.prompts ?? []))
      .catch((err) => setError(err.message))
  }, [])

  const isNewPrompt = promptChoice === NEW_PROMPT
  const savedPrompt = isNewPrompt ? null : prompts.find((p) => p.id === promptChoice)
  const promptReady = isNewPrompt ? Boolean(gradingPrompt.trim()) : Boolean(savedPrompt)

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const chosen = (datasets ?? []).filter((d) => selected.has(d.id))
  // Titles aren't unique, so the created time (then the topic) tells two similarly titled datasets apart.
  const datasetOptions = (datasets ?? [])
    .filter((d) => !selected.has(d.id))
    .map((d) => ({
      value: d.id,
      label: d.name,
      suffix: `(${d.paper_count})`,
      detail: `${formatDateTime(d.created_at)} · ${d.verbose_query}`,
      keywords: d.verbose_query,
    }))

  const configured = hasConfiguredProvider(providers)
  const choice = usableAiChoice(aiChoice, providers) || defaultAiChoice(providers)

  const runEvaluation = async (e) => {
    e.preventDefault()
    if (!configured) {
      navigate('/settings')
      return
    }
    if (!selected.size || !promptReady) return

    saveEvaluateAiChoice(choice)

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
          ...(isNewPrompt ? { grading_prompt: gradingPrompt.trim() } : { prompt_id: promptChoice }),
          ai_api: choice.ai_api,
          ai_model: choice.ai_model,
        },
        { signal: controller.signal }
      )
      await driveAnalysisRun(run.id, controller.signal, (update) => {
        setProgress({ processed: update.candidate_papers.length - update.remaining, remaining: update.remaining })
      })
      navigate(`/results/${run.id}`)
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <PageShell
      title="Evaluate Papers"
      icon={navIcon('/evaluate')}
      description="Describe specifically what you are looking for and the AI model will grade each paper abstract from a dataset against your criteria. Results are saved and papers are shown in order of relevance."
    >
      <Card>
        <form onSubmit={runEvaluation} className="flex flex-col gap-4">
          <div>
            <span className="block text-sm font-medium text-gray-700">Datasets to evaluate</span>
            <div className="mt-1 flex flex-wrap items-start gap-2">
              <div className="w-full">
                <Combobox
                  options={datasetOptions}
                  value={null}
                  onChange={toggle}
                  blurOnChoose
                  placeholder={
                    chosen.length
                      ? `${chosen.length} dataset${chosen.length === 1 ? '' : 's'} selected`
                      : datasets && datasets.length === 0
                        ? 'No datasets yet'
                        : 'Choose datasets or type to search'
                  }
                  emptyText={datasetOptions.length ? 'No datasets match.' : 'No more datasets.'}
                />
              </div>
              {chosen.map((d) => (
                <span
                  key={d.id}
                  className="inline-flex items-center gap-1 rounded-full bg-blue-600 py-1 pl-3 pr-1.5 text-sm text-white dark:bg-blue-950 dark:text-blue-300"
                >
                  {d.name} ({d.paper_count})
                  <button
                    type="button"
                    onClick={() => toggle(d.id)}
                    aria-label={`Remove ${d.name}`}
                    className="rounded-full p-0.5 hover:bg-blue-700 dark:hover:bg-blue-900"
                  >
                    <X size={14} />
                  </button>
                </span>
              ))}
            </div>
            {chosen.length ? (
              <p className="mt-2 text-sm text-gray-500">
                {chosen.reduce((sum, d) => sum + d.paper_count, 0).toLocaleString()} total papers{chosen.length > 1 ? ' (duplicates are skipped)' : ''}
              </p>
            ) : null}
            {datasets && datasets.length === 0 ? (
              <p className="mt-1 text-sm text-gray-500">No datasets yet - create one from Discover Papers.</p>
            ) : null}
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">Scoring prompt</span>
            <div className="mt-1 max-w-xs">
              <PromptCombobox prompts={prompts} value={promptChoice} onChange={setPromptChoice} />
            </div>
          </div>

          {isNewPrompt ? (
            <div>
              <label className="block text-sm font-medium text-gray-700">Ideal research paper contents</label>
              <AutoGrowTextarea
                value={gradingPrompt}
                onChange={(e) => setGradingPrompt(e.target.value)}
                placeholder="Precisely what should a paper show to be relevant?"
                rows={3}
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          ) : savedPrompt ? (
            <div className="rounded-md bg-gray-50 p-3">
              <p className="whitespace-pre-wrap text-sm text-gray-700">{savedPrompt.description}</p>
              <p className="mt-2 text-xs text-gray-400">
                {savedPrompt.example_count} example{savedPrompt.example_count === 1 ? '' : 's'}
              </p>
            </div>
          ) : null}

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
            disabled={!providers || status === 'loading' || (configured && (!selected.size || !promptReady))}
            // White while it can't be run yet (key status still loading, no dataset
            // or prompt), blue once it can. While a run is going it stays blue,
            // just faded.
            className={`self-start rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
              status === 'loading'
                ? 'border-blue-600 bg-blue-600 text-white opacity-50'
                : 'border-blue-600 bg-blue-600 text-white hover:border-blue-700 hover:bg-blue-700 disabled:border-gray-200 disabled:bg-surface disabled:text-gray-400 disabled:hover:bg-surface'
            }`}
          >
            {providers && !configured ? 'Configure API key' : status === 'loading' ? 'Evaluating…' : 'Run Evaluation'}
          </button>
        </form>
      </Card>
    </PageShell>
  )
}
