import { useRef, useState } from 'react'

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
        <span className="shrink-0 text-sm text-gray-500">{result.year ?? '—'}</span>
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

function App() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [status, setStatus] = useState('idle') // idle | loading | error | done
  const [error, setError] = useState(null)
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

    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(trimmed)}`, {
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
        <h1 className="text-2xl font-semibold text-gray-900">Lit Review Assistant</h1>
        <p className="mt-1 text-sm text-gray-500">
          Search OpenAlex for papers relevant to your research question.
        </p>

        <form onSubmit={runSearch} className="mt-6 flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. nitrogen cycling in peatland soils"
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

        {status === 'error' ? (
          <p className="mt-4 text-sm text-red-600">{error}</p>
        ) : null}

        {status === 'done' ? (
          <p className="mt-6 text-sm text-gray-500">{results.length} results</p>
        ) : null}

        <ul className="mt-4 flex flex-col gap-3">
          {results.map((result, index) => (
            <ResultCard key={result.id ?? `${result.doi ?? result.title}-${index}`} result={result} />
          ))}
        </ul>
      </div>
    </div>
  )
}

export default App
