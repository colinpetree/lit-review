import Modal from './Modal'
import { sourceLabel } from '../lib/paperSources'
import { formatDateTime } from '../lib/format'
import { groupBySource, hitsText, summarizeRetrieval } from '../lib/retrieval'

// One search (or one check for new papers): each source with its queries and how many papers
// each matched against how many were kept. A search the limit stopped is amber.
function SearchTable({ title, retrieval }) {
  return (
    <section>
      <h3 className="text-sm font-medium text-gray-500">{title}</h3>
      <div className="mt-2 flex flex-col gap-3">
        {groupBySource(retrieval).map(({ source, entries }) => (
          <div key={source}>
            <p className="font-medium text-gray-700">{sourceLabel(source)}</p>
            <ul className="mt-1 flex flex-col gap-0.5">
              {entries.map((entry) => (
                <li key={entry.query} className="flex justify-between gap-4">
                  <span className="min-w-0 truncate" title={entry.query}>
                    {entry.query}
                  </span>
                  <span className={`shrink-0 ${entry.capped ? 'text-amber-700 dark:text-amber-400' : ''}`}>
                    {hitsText(entry)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  )
}

// All the detail behind a dataset's "Search completeness": how many papers each kept, the
// numbers per source and query for the search and for the latest check for new papers, and
// why a source itself stopped short (rare; each once).
export default function SearchCompletenessModal({ dataset, onClose }) {
  const search = dataset.retrieval
  const check = dataset.last_refresh?.retrieval
  const all = [...(search || []), ...(check || [])]
  const summary = summarizeRetrieval(all)

  return (
    <Modal title="Search completeness" onClose={onClose} wide>
      <div className="mt-4 flex max-h-[70vh] flex-col gap-5 overflow-y-auto pr-1 text-sm text-gray-700">
        {dataset.search_limit ? (
          <div>
            <h3 className="text-sm font-medium text-gray-500">Papers kept per search</h3>
            <p className="mt-1">The {dataset.search_limit} most relevant papers from each source and query.</p>
          </div>
        ) : null}

        {search?.length ? <SearchTable title="Search" retrieval={search} /> : null}
        {check?.length ? (
          <SearchTable
            title={`Latest check for new papers${
              formatDateTime(dataset.last_refresh.at) ? ` (${formatDateTime(dataset.last_refresh.at)})` : ''
            }`}
            retrieval={check}
          />
        ) : null}

        {summary?.reasons.length ? (
          <div className="flex flex-col gap-1 border-t border-gray-100 pt-4 text-amber-700 dark:text-amber-400">
            {summary.reasons.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}
