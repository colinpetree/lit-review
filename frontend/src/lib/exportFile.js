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

// An Error from a refused response: the server's own message when it sent one, else the
// fallback and the status. The status is kept for callers that treat some specially.
export async function responseError(res, fallback) {
  let message
  try {
    message = (await res.json()).error
  } catch {
    // not JSON: the status below is all there is to say
  }
  const error = new Error(message || `${fallback} (${res.status}).`)
  error.status = res.status
  return error
}

// Save a successful response's body as a file, under the name the server chose.
export async function saveResponseAsFile(res) {
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

// POST the export request and save the file it answers with. Goes through apiFetch so
// the request carries the app's secret, which a plain link to the file could not.
export async function downloadExport(url, body) {
  const res = await apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await responseError(res, 'The export failed')
  await saveResponseAsFile(res)
}

// The Export entries for a MoreMenu (an array, to spread into its items). `url` is the
// page's export route, `all` and `shown` the ids of the papers the server would export in
// full and of those the page's filter and sort currently show (in that order). With no
// filter on, the two are the same: one "Export" entry listing the formats. With one on there
// are two entries, "Export shown" and "Export all", each listing the formats, so the choice
// is made once rather than beside every format. `onError(message)` is called when a download
// fails.
export function exportMenuItems({ url, all, shown, filterActive, onError }) {
  const start = (format, paperIds) => {
    downloadExport(url, paperIds ? { format, paper_ids: paperIds } : { format }).catch((err) => onError(err.message))
  }
  const formats = (paperIds) => FORMATS.map(({ id, label }) => ({ label, onClick: () => start(id, paperIds) }))
  if (!filterActive) return [{ label: `Export (${all.length})`, icon: Download, submenu: formats(null) }]
  return [
    { label: `Export shown (${shown.length})`, icon: Download, submenu: formats(shown) },
    { label: `Export all (${all.length})`, icon: Download, submenu: formats(null) },
  ]
}
