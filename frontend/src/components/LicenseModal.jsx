import TextModal from './TextModal'
// The repo's own LICENSE, embedded when the page is built, so what the user reads here is the
// file that ships inside the app and can never drift from it.
import licenseText from '../../../LICENSE?raw'

// The full license, in a box that scrolls.
export default function LicenseModal({ onClose }) {
  return <TextModal title="License" text={licenseText.trim()} onClose={onClose} />
}
