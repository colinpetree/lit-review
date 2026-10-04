import { useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import { Card } from '../ui'
import { fetchJson } from '../../lib/api'

// What this copy is and where it keeps things, so a user (or whoever is helping them) can
// find the data and the log without guessing a hidden folder.
export default function AboutCard() {
  const [about, setAbout] = useState(null)
  useEffect(() => {
    fetchJson('/api/about')
      .then(setAbout)
      .catch(() => {})
  }, [])

  const rows = [
    ['Version', about?.version],
    ['Data folder', about?.data_dir],
    ['Log folder', about?.log_dir],
  ]
  return (
    <Card className="flex flex-col gap-5">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-800 [--icon-nudge:-1px]">
        <Info size={18} className="shrink-0" />
        About this copy
      </h2>
      {rows.map(([label, value]) => (
        <div key={label} className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">{label}</p>
          <p className="break-all font-mono text-xs text-gray-800">{value ?? '…'}</p>
        </div>
      ))}
      <p className="text-xs text-gray-400">
        Your datasets, results and prompts are in the data folder. Your API keys are kept separately, in this
        computer’s settings folder for the app. If something goes wrong, the log folder has details that help
        whoever is fixing it.
      </p>
    </Card>
  )
}
