import { useEffect } from 'react'
import { X } from 'lucide-react'

// Centered dialog with a backdrop, an X in the top right, and Escape / backdrop
// click to close. While `busy` (a request in flight) it can't be dismissed.
export default function Modal({ title, onClose, busy = false, children }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={() => !busy && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="relative w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          disabled={busy}
          className="absolute right-3 top-3 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50"
        >
          <X size={18} />
        </button>
        <h2 className="pr-8 text-lg font-semibold text-gray-900">{title}</h2>
        {children}
      </div>
    </div>
  )
}
