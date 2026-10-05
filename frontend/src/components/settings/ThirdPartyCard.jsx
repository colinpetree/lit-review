import { useState } from 'react'
import { Card } from '../ui'
import ThirdPartyNoticesModal from '../ThirdPartyNoticesModal'

// The licenses of the open-source software inside Lit Review, one click away from the
// license itself. The list is read from the app when the dialog opens.
export default function ThirdPartyCard() {
  const [open, setOpen] = useState(false)
  return (
    <Card className="flex flex-col gap-1.5">
      <p className="text-sm font-medium text-gray-700">Third-party software</p>
      <p className="text-xs text-gray-400">
        Lit Review includes open-source software from other people, each under its own license. Their notices are listed
        here.
      </p>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
      >
        View third-party notices
      </button>
      {open && <ThirdPartyNoticesModal onClose={() => setOpen(false)} />}
    </Card>
  )
}
