import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

// Centered dialog with a backdrop, an X in the top right, and Escape / backdrop
// click to close. While `busy` (a request in flight) it can't be dismissed.
// wide is for dialogs that hold a list or table.
// raised is for a dialog that can open while another dialog (Settings) is already up, and must be above it.
// closeOnBackdrop={false} is for dialogs with text fields, where a stray click
// outside would throw away what was typed. Otherwise a backdrop click only
// closes when the press started on the backdrop too, so dragging to select text
// and releasing outside the dialog doesn't close it.
export default function Modal({ title, onClose, busy = false, closeOnBackdrop = true, wide = false, raised = false, children }) {
  const pressStartedOnBackdrop = useRef(false)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  return (
    <div
      className={`fixed inset-0 ${raised ? 'z-[60]' : 'z-50'} flex items-center justify-center bg-black/40 px-4`}
      onMouseDown={(e) => {
        pressStartedOnBackdrop.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (closeOnBackdrop && !busy && pressStartedOnBackdrop.current && e.target === e.currentTarget) onClose()
        pressStartedOnBackdrop.current = false
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className={`relative w-full rounded-lg bg-surface p-6 shadow-xl ${wide ? 'max-w-2xl' : 'max-w-md'}`}
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
        <h2 className="pr-8 text-lg font-semibold text-gray-800">{title}</h2>
        {children}
      </div>
    </div>
  )
}
