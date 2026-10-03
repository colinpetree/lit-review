import { Download } from 'lucide-react'
import { apiFetch } from './api'

const FORMATS = [
  { id: 'csv', label: 'CSV' },
  { id: 'ris', label: 'RIS' },
  { id: 'bibtex', label: 'BibTeX' },
]

// The file name the server chose, from its Content-Disposition header.
export function filenameFromDisposition(header) {
  const match = /filename="([^"]+)"/.exec(header || '')
  return match ? match[1] : 'papers'
}

// POST the export request and save the file it answers with. Goes through apiFetch so
// the request carries the app's secret, which a plain link to the file could not.
export async function downloadExport(url, body) {
  const res = await apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let message
    try {
      message = (await res.json()).error
    } catch {
      // not JSON: the status below is all there is to say
    }
    const error = new Error(message || `The export failed (${res.status}).`)
    error.status = res.status
    throw error
  }
  const blob = await res.blob()
  const link = document.createElement('a')
  const objectUrl = URL.createObjectURL(blob)
  link.href = objectUrl
  link.download = filenameFromDisposition(res.headers.get('Content-Disposition'))
  document.body.appendChild(link)
  link.click()
  link.remove()
  // After the browser has started the save.
  setTimeout(() => URL.revokeObjectURL(objectUrl), 10_000)
}

// The "Export" entry for a MoreMenu. `url` is the page's export route, `all` and
// `shown` the ids of the papers the server would export in full and of those the page's
// filter and sort currently show (in that order). With no filter on, the two are the same,
// so each format is one choice; with one on, each format can be exported either way.
// `onError(message)` is called when a download fails.
export function exportMenuItem({ url, all, shown, filterActive, onError }) {
  const start = (format, paperIds) => {
    downloadExport(url, paperIds ? { format, paper_ids: paperIds } : { format }).catch((err) => onError(err.message))
  }
  const submenu = FORMATS.flatMap(({ id, label }) =>
    filterActive
      ? [
          { label: `${label}, shown (${shown.length})`, onClick: () => start(id, shown) },
          { label: `${label}, all (${all.length})`, onClick: () => start(id, null) },
        ]
      : [{ label: `${label} (${all.length})`, onClick: () => start(id, null) }]
  )
  return { label: 'Export', icon: Download, submenu }
}
