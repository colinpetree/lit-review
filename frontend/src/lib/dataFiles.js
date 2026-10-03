import { apiFetch } from './api'
import { responseError, saveResponseAsFile } from './exportFile'

// Download the whole database as one file (GET /api/data/backup). Goes through apiFetch so
// the request carries the app's secret, which a plain link to the file could not.
export async function downloadBackup() {
  const res = await apiFetch('/api/data/backup')
  if (!res.ok) throw await responseError(res, 'The backup failed')
  await saveResponseAsFile(res)
}

// Replace all the data with a backup file the user chose. The file itself is the request
// body (not a form), so the server can read it in pieces without holding it in memory.
// Returns the server's answer ({ message, safety_copy }).
export async function restoreBackup(file) {
  const res = await apiFetch('/api/data/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  })
  if (!res.ok) throw await responseError(res, 'The restore failed')
  return res.json()
}
