import Modal from './Modal'

// A long text (a license, a list of notices) in a wide dialog, in a box that scrolls.
export default function TextModal({ title, text, onClose }) {
  return (
    <Modal title={title} onClose={onClose} wide>
      <pre className="mt-4 max-h-[70vh] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-gray-200 p-4 font-sans text-xs leading-relaxed text-gray-700">
        {text}
      </pre>
    </Modal>
  )
}
