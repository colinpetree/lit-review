import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import {
  POLL_FAST_MS,
  getModalDismissed,
  installUpdate,
  modalKey,
  rememberModalDismissed,
  shouldOfferModal,
  useUpdateStatus,
} from '../lib/updateCheck'

const noop = () => {}
const UpdateContext = createContext({
  status: null,
  refresh: noop,
  install: noop,
  installing: false,
  installError: '',
  modalOpen: false,
  closeModal: noop,
})

// One look at the app's update status for everything that shows it: the "update ready" dialog, the
// banner at the top of the page and the Settings card, so they agree and the app is asked once.
export function UpdateProvider({ children }) {
  const { status, refresh, setStatus } = useUpdateStatus()
  const [dismissed, setDismissed] = useState(getModalDismissed)
  const [starting, setStarting] = useState(false)
  const [installError, setInstallError] = useState('')

  // Pressed Install update (or the app already says it is applying): from here the app restarts.
  const installing = starting || status?.state === 'applying'

  const install = useCallback(async () => {
    setStarting(true)
    setInstallError('')
    try {
      await installUpdate()
      setStatus((current) => ({ ...current, state: 'applying' }))
      setTimeout(refresh, POLL_FAST_MS)
    } catch (err) {
      setInstallError(err.message || 'The update could not be started.')
      setStarting(false)
    }
  }, [refresh, setStatus])

  const closeModal = useCallback(() => {
    if (installing) return
    const key = modalKey(status)
    if (key) {
      rememberModalDismissed(key)
      setDismissed(key)
    }
    setInstallError('')
  }, [installing, status])

  const modalOpen = installing || shouldOfferModal(status, dismissed)

  const value = useMemo(
    () => ({ status, refresh, install, installing, installError, modalOpen, closeModal }),
    [status, refresh, install, installing, installError, modalOpen, closeModal],
  )
  return <UpdateContext.Provider value={value}>{children}</UpdateContext.Provider>
}

export const useUpdates = () => useContext(UpdateContext)
