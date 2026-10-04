import Modal from './Modal'
// The repo's own LICENSE, embedded when the page is built, so what the user reads here is the
// file that ships beside the app and can never drift from it.
import licenseText from '../../../LICENSE?raw'

// The full license, in a box that scrolls.
export default function LicenseModal({ onClose }) {
  return (
    <Modal title="License" onClose={onClose} wide>
      <pre className="mt-4 max-h-[70vh] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-gray-200 p-4 font-sans text-xs leading-relaxed text-gray-700">
        {licenseText.trim()}
      </pre>
    </Modal>
  )
}
