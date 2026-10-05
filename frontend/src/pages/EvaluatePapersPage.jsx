import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useSettingsModal } from '../components/SettingsModalProvider'
import { X } from 'lucide-react'
import Checkbox from '../components/Checkbox'
import Combobox from '../components/Combobox'
import { PageShell, Card, TextLink } from '../components/ui'
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
import ConfirmModal from '../components/ConfirmModal'
import useRunEstimate from '../lib/useRunEstimate'
import { formatUsd, getSpendThreshold, limitFor, needsConfirmation } from '../lib/spendSetting'

export default function EvaluatePapersPage() {
  const navigate = useNavigate()
  const { openSettings } = useSettingsModal()
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
  // Retracted papers are not graded (and paid for) unless the user asks for them.
  const [includeRetracted, setIncludeRetracted] = useState(false)
  // NEW_PROMPT (write the ideal research paper contents below) or a saved prompt's id.
  const [promptChoice, setPromptChoice] = useState(NEW_PROMPT)
  const [prompts, setPrompts] = useState([])
  // Starts from the model of the last run (saved when a run starts); one that is
  // no longer listed or configured falls back to the default.
  const [aiChoice, setAiChoice] = useState(loadEvaluateAiChoice)
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)
  const [progress, setProgress] = useState(null)
  // A run whose estimate is above the user's threshold, waiting for their yes: { usd, papers, limit }.
  const [confirming, setConfirming] = useState(null)
  // Waiting for an estimate that the run's start needs and the form did not have yet.
  const [pricing, setPricing] = useState(false)
  // Aborts a prior in-flight submission before starting a new one - guards
  // against a rapid double-submit (double-click, double Enter) firing two
  // real analysis runs (and paying for LLM grading twice) before the
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

  // What would be sent to start the run, or null while the form is not ready to run. The
  // same body prices it (POST /api/analysis-runs/estimate) and, with a limit added, creates it.
  const runRequest =
    configured && selected.size && promptReady && choice
      ? {
          dataset_ids: [...selected],
          ...(isNewPrompt ? { grading_prompt: gradingPrompt.trim() } : { prompt_id: promptChoice }),
          ai_api: choice.ai_api,
          ai_model: choice.ai_model,
          include_retracted: includeRetracted,
        }
      : null
  const { estimate, failed: estimateFailed, loading: estimating } = useRunEstimate(runRequest)

  // Asks the user first when the estimate is above their threshold (Settings), then starts.
  const runEvaluation = async (e) => {
    e.preventDefault()
    if (!configured) {
      openSettings('ai')
      return
    }
    if (!runRequest) return

    const threshold = getSpendThreshold()
    if (threshold === null) {
      startRun(null)
      return
    }
    // The estimate on screen, or one asked for now if the form changed a moment ago.
    let priced = estimate
    if (!priced) {
      setPricing(true)
      setError(null)
      try {
        priced = await postJson('/api/analysis-runs/estimate', runRequest)
      } catch (err) {
        setError(`The cost could not be estimated, so nothing was started. ${err.message}`)
        return
      } finally {
        setPricing(false)
      }
    }
    if (needsConfirmation(priced.usd, threshold)) {
      setConfirming({ usd: priced.usd, papers: priced.papers, threshold, limit: limitFor({ usd: priced.usd, threshold, confirmed: true }) })
      return
    }
    startRun(limitFor({ usd: priced.usd, threshold, confirmed: false }))
  }

  const startRun = async (maxUsd) => {
    saveEvaluateAiChoice(choice)

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setStatus('loading')
    setError(null)
    setProgress(null)

    let createdId = null
    try {
      const run = await postJson(
        '/api/analysis-runs',
        { ...runRequest, ...(maxUsd === null ? {} : { max_usd: maxUsd }) },
        { signal: controller.signal }
      )
      createdId = run.id
      await driveAnalysisRun(run.id, controller.signal, (update) => {
        setProgress({ processed: update.candidate_papers.length - update.remaining, remaining: update.remaining })
      })
      navigate(`/results/${run.id}`)
    } catch (err) {
      if (err.name === 'AbortError') return
      // The run's spending limit stopped it: not a failure. What was graded is saved, and
      // the run page offers to raise the limit and carry on.
      if (err.limitReached && createdId !== null) {
        navigate(`/results/${createdId}`)
        return
      }
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
                  disabled={datasets?.length === 0}
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
              <p className="mt-1 text-sm text-gray-500">No datasets yet - create one from <TextLink to="/discover">Discover Papers</TextLink>.</p>
            ) : null}
          </div>

          <div>
            <span className="block text-sm font-medium text-gray-700">Grading prompt</span>
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
                maxLength={4000}
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

          <div>
            <Checkbox checked={includeRetracted} onChange={setIncludeRetracted}>
              Include retracted papers
            </Checkbox>
            <p className="mt-1 pl-[26px] text-xs text-gray-400">
              Papers a source says were retracted are left out of the evaluation unless this is checked.
            </p>
          </div>

          {error ? <p className="text-sm text-red-600 dark:text-red-400">{error}</p> : null}
          {status === 'loading' ? (
            <StageIndicator
              label={
                progress
                  ? `Grading papers… ${progress.processed} done, ${progress.remaining} remaining`
                  : 'Grading papers…'
              }
            />
          ) : null}

          {runRequest ? (
            <p className="text-sm text-gray-500" aria-live="polite">
              {estimate
                ? `About ${formatUsd(estimate.usd)} for ${estimate.papers.toLocaleString()} paper${estimate.papers === 1 ? '' : 's'}${
                    estimate.basis === 'history' ? ', based on your earlier runs with this model' : ''
                  }. An estimate: the real cost can differ.`
                : estimateFailed
                  ? 'The cost could not be estimated.'
                  : estimating
                    ? 'Estimating the cost…'
                    : null}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={!providers || status === 'loading' || pricing || (configured && (!selected.size || !promptReady))}
            // White while it can't be run yet (key status still loading, no dataset
            // or prompt), blue once it can. While a run is going it stays blue,
            // just faded.
            className={`self-start rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
              status === 'loading'
                ? 'border-blue-600 bg-blue-600 text-white opacity-50'
                : 'border-blue-600 bg-blue-600 text-white hover:border-blue-700 hover:bg-blue-700 disabled:border-gray-200 disabled:bg-surface disabled:text-gray-400 disabled:hover:bg-surface'
            }`}
          >
            {providers && !configured ? 'Configure API key' : status === 'loading' ? 'Evaluating…' : pricing ? 'Estimating…' : 'Run Evaluation'}
          </button>
        </form>
      </Card>
      {confirming ? (
        <ConfirmModal
          title="Run this evaluation?"
          message={`This is estimated to cost about ${formatUsd(confirming.usd)} for ${confirming.papers.toLocaleString()} papers, ${
            confirming.threshold === 0
              ? 'and you asked to be asked before every run'
              : `more than the ${formatUsd(confirming.threshold)} you asked to be asked about`
          }. Grading stops at about ${formatUsd(confirming.limit)}, and can pass that by up to one batch of 20 papers. You can raise the limit later from the run.`}
          confirmLabel="Run evaluation"
          // Not awaited: the modal closes now and the page shows the run's progress.
          onConfirm={() => {
            startRun(confirming.limit)
          }}
          onClose={() => setConfirming(null)}
        />
      ) : null}
    </PageShell>
  )
}
