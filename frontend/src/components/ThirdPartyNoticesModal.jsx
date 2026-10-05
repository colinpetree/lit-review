import Modal from './Modal'
import TextModal from './TextModal'
import { useNotices } from '../lib/notices'

// The licenses of the software Lit Review includes, in the same box as the license. While they
// load, or if they cannot be loaded (the message says why), a short note with a Retry instead.
export default function ThirdPartyNoticesModal({ onClose }) {
  const { text, error, loading, retry } = useNotices()
  if (text) return <TextModal title="Third-party notices" text={text.trim()} onClose={onClose} />
  return (
    <Modal title="Third-party notices" onClose={onClose} wide>
      <p className="mt-4 text-sm text-gray-600" role={error ? 'alert' : 'status'}>
        {loading ? 'Loading...' : error}
      </p>
      {!loading && (
        <button
          type="button"
          onClick={retry}
          className="mt-3 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
        >
          Try again
        </button>
      )}
    </Modal>
  )
}
