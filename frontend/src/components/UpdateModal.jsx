import Modal from './Modal'
import Spinner from './Spinner'
import { installsAtNextStart } from '../lib/updateCheck'
import { useUpdates } from './UpdateProvider'

// "A new version is ready": shown when an update has finished downloading, and at every start that finds
// one waiting, to someone who installs updates themselves. They can install it now or put it off (Not now,
// the X, Escape or a click outside all do the same); Settings keeps the same Install update button.
// It sits above Settings (raised): a download finishing while someone watches it there must show.
export default function UpdateModal() {
  const { status, installing, installError, modalOpen, install, closeModal } = useUpdates()
  if (!modalOpen) return null

  if (installing) {
    return (
      <Modal title="Installing the update" onClose={closeModal} busy raised>
        <div className="mt-3 flex items-start gap-3 text-sm text-gray-600" role="status">
          <Spinner className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Lit Review is installing version {status?.latest} and will restart. A new window opens when it is done; you
            can close this one. Your data is kept.
          </p>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title="Update ready" onClose={closeModal} raised>
      <p className="mt-2 text-sm text-gray-600">
        {installsAtNextStart(status)
          ? 'There is an update that is ready to install. This update will be applied automatically on the next start.'
          : `A new version of Lit Review${status?.latest ? ` (${status.latest})` : ''} is downloaded and ready to apply. It will only take a moment to restart.`}
      </p>
      {status?.notice ? <p className="mt-2 text-sm text-gray-600">{status.notice}</p> : null}
      {installError ? (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {installError}
        </p>
      ) : null}
      <div className="mt-6 flex justify-end gap-2">
        <button
          type="button"
          onClick={closeModal}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
        >
          Not now
        </button>
        <button
          type="button"
          onClick={install}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          Install update
        </button>
      </div>
    </Modal>
  )
}
