import Modal from './Modal'
import Spinner from './Spinner'
import { installsAtNextStart } from '../lib/updateCheck'
import { useUpdates } from './UpdateProvider'

// "Welcome to Lit Review X" is shown first, once, by the copy the update helper just started, whether the
// update was installed by the button or by itself at launch. "Installing the update" is also what a launch
// that installs by itself shows while it hands over, so both ways of updating look the same.
//
// "A new version is ready": shown when an update has finished downloading, and at every start that finds
// one waiting, to someone who installs updates themselves. They can install it now or put it off (Not now,
// the X, Escape or a click outside all do the same); Settings keeps the same Install update button.
// It sits above Settings (raised): a download finishing while someone watches it there must show.
export default function UpdateModal() {
  const { status, installing, installError, modalOpen, install, closeModal, welcomeVersion, closeWelcome, stuck, updated, closeUpdated } =
    useUpdates()

  // This tab watched an install and the app has since answered as a different run of itself: the new copy is
  // up (and has opened its own window), or the old one was put back after a failure. A tab cannot close itself.
  if (updated) {
    const failed = status?.state === 'failed'
    return (
      <Modal title={failed ? 'The update was not installed' : 'Lit Review was updated'} onClose={closeUpdated} raised>
        <p className="mt-2 text-sm text-gray-600" role="status">
          {failed
            ? status?.error || 'The update could not be installed, so Lit Review is still on the previous version.'
            : `Lit Review is now on version ${status?.current}. A new window should have opened. You can safely close this tab.`}
        </p>
        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={closeUpdated}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
          >
            OK
          </button>
        </div>
      </Modal>
    )
  }

  if (welcomeVersion) {
    return (
      <Modal title={`Welcome to Lit Review ${welcomeVersion}`} onClose={closeWelcome} raised>
        <p className="mt-2 text-sm text-gray-600" role="status">
          Version {welcomeVersion} was successfully installed.
        </p>
        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={closeWelcome}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
          >
            OK
          </button>
        </div>
      </Modal>
    )
  }

  if (!modalOpen) return null

  if (installing) {
    return (
      <Modal title="Installing the update" onClose={closeModal} busy={!stuck} raised>
        <div className="mt-3 flex items-start gap-3 text-sm text-gray-600" role="status">
          <Spinner className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Lit Review is installing version {status?.latest} and will restart. A new window opens when it is done. You
            can safely close this one. Your data is kept.
            {stuck ? ' This is taking longer than expected. Lit Review opens a new window when it is done.' : ''}
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
