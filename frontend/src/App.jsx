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

function App() {
  const [query, setQuery] = useState('')
  const [aiAssisted, setAiAssisted] = useState(false)
  const [results, setResults] = useState([])
  const [cost, setCost] = useState(null)
  const [status, setStatus] = useState('idle') // idle | loading | error | done
  const [error, setError] = useState(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Tracks the in-flight request so a slower, older response can never
  // overwrite the results of a newer one - the only signal that survives
  // is the most recently submitted query's.
  const activeRequestRef = useRef(null)

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

    try {
      const res = aiAssisted
        ? await fetch('/api/review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question: trimmed }),
            signal: controller.signal,
          })
        : await fetch(`/api/search?q=${encodeURIComponent(trimmed)}`, {
            signal: controller.signal,
          })

      let data
      try {
        data = await res.json()
      } catch {
        // A non-JSON body (an HTML error page from a proxy in front of the
        // backend, for example) means we can't trust anything but the status.
        throw new Error(`Unexpected response from the server (${res.status}).`)
      }

      if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
      setResults(data.results)
      setCost(data.cost ?? null)
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

        {status === 'error' ? (
          <p className="mt-4 text-sm text-red-600">{error}</p>
        ) : null}

        {status === 'done' ? (
          <p className="mt-6 text-sm text-gray-500">
            {results.length} results
            {cost ? ` · $${cost.usd.toFixed(4)} (${cost.input_tokens + cost.output_tokens} tokens)` : ''}
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
