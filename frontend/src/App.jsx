import { useEffect, useRef, useState } from 'react'

function ScoreBadge({ score }) {
  if (score === null || score === undefined) return null
  const color =
    score >= 70 ? 'bg-green-100 text-green-800' : score >= 40 ? 'bg-yellow-100 text-yellow-800' : 'bg-gray-100 text-gray-600'
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>
      {score}/100
    </span>
  )
}

function ResultCard({ result }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <li className="border border-gray-200 rounded-lg p-4 hover:border-gray-300">
      <div className="flex items-start justify-between gap-4">
        <h3 className="font-medium text-gray-900">
          {result.url ? (
            <a
              href={result.url}
              target="_blank"
              rel="noreferrer"
              className="hover:underline"
            >
              {result.title}
            </a>
          ) : (
            result.title
          )}
        </h3>
        <div className="flex shrink-0 items-center gap-2">
          <ScoreBadge score={result.score} />
          <span className="text-sm text-gray-500">{result.year ?? '—'}</span>
        </div>
      </div>

      <p className="mt-1 text-sm text-gray-500">
        {(() => {
          const named = result.authors.filter(Boolean)
          return (
            <>
              {named.slice(0, 5).join(', ')}
              {named.length > 5 ? ', et al.' : ''}
            </>
          )
        })()}
        {result.venue ? ` · ${result.venue}` : ''}
        {' · '}
        {result.citation_count} citation{result.citation_count === 1 ? '' : 's'}
        {result.is_review ? ' · review' : ''}
      </p>

      {result.rationale ? (
        <p className="mt-2 text-sm text-gray-700 italic">{result.rationale}</p>
      ) : null}

      {result.abstract ? (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-sm text-blue-600 hover:underline"
          >
            {expanded ? 'Hide abstract' : 'Show abstract'}
          </button>
          {expanded ? (
            <p className="mt-2 text-sm text-gray-700">{result.abstract}</p>
          ) : null}
        </div>
      ) : (
        <p className="mt-2 text-sm text-gray-400 italic">No abstract available</p>
      )}
    </li>
  )
}

function SettingsPanel({ onClose }) {
  const [hasKey, setHasKey] = useState(null)
  const [input, setInput] = useState('')
  const [status, setStatus] = useState('idle') // idle | saving | error
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/settings/api-key')
      .then((res) => res.json())
      .then((data) => setHasKey(Boolean(data.anthropic)))
      .catch(() => setHasKey(false))
  }, [])

  const save = async (e) => {
    e.preventDefault()
    setStatus('saving')
    setError(null)
    try {
      const res = await fetch('/api/settings/api-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'anthropic', api_key: input }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
      setHasKey(true)
      setInput('')
      setStatus('idle')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  const remove = async () => {
    await fetch('/api/settings/api-key', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'anthropic' }),
    })
    setHasKey(false)
  }

  return (
    <div className="fixed inset-0 z-10 flex items-start justify-center bg-black/30 pt-24">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">AI provider settings</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">
            ✕
          </button>
        </div>

        <p className="mt-2 text-sm text-gray-500">
          Anthropic (Claude) API key, used for query expansion and relevance scoring.
          Stored locally in an encrypted file on this machine, never sent anywhere but
          Anthropic's API.
        </p>

        <p className="mt-3 text-sm">
          Status:{' '}
          {hasKey === null ? 'checking…' : hasKey ? (
            <span className="text-green-700">key configured</span>
          ) : (
            <span className="text-gray-500">no key set</span>
          )}
        </p>

        <form onSubmit={save} className="mt-3 flex gap-2">
          <input
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="sk-ant-..."
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={status === 'saving' || !input.trim()}
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            Save
          </button>
        </form>

        {error ? <p className="mt-2 text-sm text-red-600">{error}</p> : null}

        {hasKey ? (
          <button
            type="button"
            onClick={remove}
            className="mt-3 text-sm text-red-600 hover:underline"
          >
            Remove saved key
          </button>
        ) : null}
      </div>
    </div>
  )
}

async function fetchJson(url, options) {
  const res = await fetch(url, options)
  let data
  try {
    data = await res.json()
  } catch {
    // A non-JSON body (an HTML error page from a proxy in front of the
    // backend, for example) means we can't trust anything but the status.
    throw new Error(`Unexpected response from the server (${res.status}).`)
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
  return data
}

function PastSearches({ datasets, onSelect }) {
  if (!datasets.length) return null
  return (
    <div className="mt-6">
      <h2 className="text-sm font-medium text-gray-700">Past searches</h2>
      <ul className="mt-2 flex flex-col gap-1">
        {datasets.map((d) => (
          <li key={d.id}>
            <button
              type="button"
              onClick={() => onSelect(d.id)}
              className="w-full rounded-md border border-gray-200 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-100"
            >
              {d.verbose_query}
              <span className="ml-2 text-gray-400">
                {d.paper_count} paper{d.paper_count === 1 ? '' : 's'}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function App() {
  const [query, setQuery] = useState('')
  const [aiAssisted, setAiAssisted] = useState(false)
  const [results, setResults] = useState([])
  const [cost, setCost] = useState(null)
  const [progress, setProgress] = useState(null) // { processed, remaining } while an AI run is in flight
  const [status, setStatus] = useState('idle') // idle | loading | error | done
  const [error, setError] = useState(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [pastDatasets, setPastDatasets] = useState([])
  // Tracks the in-flight request so a slower, older response can never
  // overwrite the results of a newer one - the only signal that survives
  // is the most recently submitted query's.
  const activeRequestRef = useRef(null)

  const refreshPastSearches = () => {
    fetch('/api/datasets')
      .then((res) => res.json())
      .then((data) => setPastDatasets(data.datasets ?? []))
      .catch(() => {})
  }

  useEffect(() => {
    refreshPastSearches()
  }, [])

  // Repeatedly processes one scoring chunk at a time until the run is
  // completed - this is what lets a reopened run (see loadDataset below)
  // skip straight to results with zero new LLM calls, since /process only
  // ever scores what's missing. Scores are merged onto the full paper list
  // (rather than replacing it with just the scored-so-far subset) so the
  // list doesn't visibly shrink and regrow as chunks land - unscored papers
  // stay visible with no score badge until their chunk completes.
  const driveAnalysisRun = async (runId, signal, allPapers) => {
    const byId = new Map(allPapers.map((p) => [p.id, p]))
    for (;;) {
      const run = await fetchJson(`/api/analysis-runs/${runId}/process`, {
        method: 'POST',
        signal,
      })
      for (const scored of run.results) byId.set(scored.id, scored)
      setResults(
        [...byId.values()].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
      )
      setCost(run.cost)
      setProgress({ processed: run.results.length, remaining: run.remaining })
      if (run.status === 'completed') break
    }
  }

  const runSearch = async (e) => {
    e.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) return

    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setStatus('loading')
    setError(null)
    setCost(null)
    setProgress(null)

    try {
      if (aiAssisted) {
        const dataset = await fetchJson('/api/datasets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: trimmed }),
          signal: controller.signal,
        })
        setResults(dataset.papers)
        setCost(dataset.cost)
        const run = await fetchJson(`/api/datasets/${dataset.id}/analysis-runs`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
        })
        await driveAnalysisRun(run.id, controller.signal, dataset.papers)
        refreshPastSearches()
      } else {
        const data = await fetchJson(`/api/search?q=${encodeURIComponent(trimmed)}`, {
          signal: controller.signal,
        })
        setResults(data.results)
      }
      setStatus('done')
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message)
      setStatus('error')
    }
  }

  const loadDataset = async (datasetId) => {
    activeRequestRef.current?.abort()
    const controller = new AbortController()
    activeRequestRef.current = controller

    setStatus('loading')
    setError(null)
    setProgress(null)

    try {
      const dataset = await fetchJson(`/api/datasets/${datasetId}`, { signal: controller.signal })
      setQuery(dataset.verbose_query)
      setAiAssisted(true)
      const latestRun = dataset.runs[0] // most recent only - see PLAN.md scope note
      if (latestRun) {
        // Reopening never calls the LLM: a completed run has nothing left to
        // score, so /process immediately returns its saved results.
        await driveAnalysisRun(latestRun.id, controller.signal, dataset.papers)
      } else {
        setResults(dataset.papers)
        setCost(dataset.cost)
      }
      setStatus('done')
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message)
      setStatus('error')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-3xl mx-auto px-4 py-10">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Lit Review Assistant</h1>
            <p className="mt-1 text-sm text-gray-500">
              Search OpenAlex for papers relevant to your research question.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
          >
            Settings
          </button>
        </div>

        <form onSubmit={runSearch} className="mt-6 flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={
              aiAssisted
                ? 'e.g. how does nitrogen cycling affect peatland carbon storage?'
                : 'e.g. nitrogen cycling in peatland soils'
            }
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={status === 'loading'}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {status === 'loading' ? 'Searching…' : 'Search'}
          </button>
        </form>

        <label className="mt-2 flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={aiAssisted}
            onChange={(e) => setAiAssisted(e.target.checked)}
          />
          Use AI to expand the query and rank results by relevance (requires an Anthropic
          API key in Settings)
        </label>

        <PastSearches datasets={pastDatasets} onSelect={loadDataset} />

        {status === 'error' ? (
          <p className="mt-4 text-sm text-red-600">{error}</p>
        ) : null}

        {status === 'loading' && progress ? (
          <p className="mt-6 text-sm text-gray-500">
            Scoring… {progress.processed} done, {progress.remaining} remaining
          </p>
        ) : null}

        {status === 'done' ? (
          <p className="mt-6 text-sm text-gray-500">
            {results.length} results
            {cost ? ` · $${cost.toFixed(4)}` : ''}
          </p>
        ) : null}

        <ul className="mt-4 flex flex-col gap-3">
          {results.map((result, index) => (
            <ResultCard key={result.id ?? `${result.doi ?? result.title}-${index}`} result={result} />
          ))}
        </ul>
      </div>

      {settingsOpen ? <SettingsPanel onClose={() => setSettingsOpen(false)} /> : null}
    </div>
  )
}

export default App
