import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  INSTALL_STUCK_MS,
  POLL_FAST_MS,
  acknowledgeInstalled,
  getModalDismissed,
  hasRestarted,
  installUpdate,
  installedVersion,
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
  welcomeVersion: null,
  closeWelcome: noop,
  stuck: false,
  updated: false,
  closeUpdated: noop,
})

// One look at the app's update status for everything that shows it: the "update ready" dialog, the
// banner at the top of the page and the Settings card, so they agree and the app is asked once.
export function UpdateProvider({ children }) {
  const { status, refresh, setStatus } = useUpdateStatus()
  const [dismissed, setDismissed] = useState(getModalDismissed)
  const [starting, setStarting] = useState(false)
  const [installError, setInstallError] = useState('')
  // Which run of the app this tab was talking to when an install began. The new copy answers with a different
  // one, which is how this tab learns the update finished (it cannot close itself: the app opened it).
  const [installFrom, setInstallFrom] = useState(null)
  // Set once this tab has watched an install, so the new copy's own window (not this one) says welcome.
  const [installedHere, setInstalledHere] = useState(false)
  const [stuckFor, setStuckFor] = useState(null)
  const [hiddenFor, setHiddenFor] = useState(null)
  // The version whose welcome was closed in this tab, so a status that was already on its way (or a failed
  // acknowledgement) cannot bring it back.
  const [welcomeClosed, setWelcomeClosed] = useState(null)

  // Pressed Install update (or the app already says it is applying): from here the app restarts.
  const applying = starting || status?.state === 'applying'
  const instance = status?.instance || null
  // Adjusting state while rendering (the documented pattern) so the very first "applying" answer is the one kept.
  if (applying && instance && installFrom === null) {
    setInstallFrom(instance)
    setInstalledHere(true)
  }
  const updated = hasRestarted(installFrom, status)
  const installing = applying && !updated

  // An install that has taken a minute is probably not going to tell this tab anything (the new copy is on
  // another port, or it failed): the dialog stops being un-closable. The app opens its own window either way.
  useEffect(() => {
    if (!installing || !installFrom) return undefined
    const timer = setTimeout(() => setStuckFor(installFrom), INSTALL_STUCK_MS)
    return () => clearTimeout(timer)
  }, [installing, installFrom])
  const stuck = installing && installFrom !== null && stuckFor === installFrom
  const installingShown = installing && hiddenFor !== installFrom

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
    if (installing) {
      if (stuck) setHiddenFor(installFrom)
      return
    }
    const key = modalKey(status)
    if (key) {
      rememberModalDismissed(key)
      setDismissed(key)
    }
    setInstallError('')
  }, [installing, stuck, installFrom, status])

  // The update finished and this tab noticed: say so once, then carry on as a normal page of the new copy.
  const closeUpdated = useCallback(() => {
    setStarting(false)
    setInstallFrom(null)
    setStuckFor(null)
    setHiddenFor(null)
  }, [])

  // "Welcome to Lit Review X": this run was started by the update helper. It goes first, so a newer update
  // waiting already does not stack a second dialog on it; that one shows once this is closed.
  const reported = installedVersion(status)
  const welcomeVersion = installedHere || reported === welcomeClosed ? null : reported
  const closeWelcome = useCallback(() => {
    setWelcomeClosed(welcomeVersion)
    setStatus((current) => (current ? { ...current, installed_version: null } : current))
    acknowledgeInstalled().catch(() => {
      // Not reached: the welcome may come back at the next status check, which is harmless.
    })
  }, [setStatus, welcomeVersion])

  const modalOpen = !welcomeVersion && !updated && (installingShown || shouldOfferModal(status, dismissed))

  const value = useMemo(
    () => ({
      status,
      refresh,
      install,
      installing,
      installError,
      modalOpen,
      closeModal,
      welcomeVersion,
      closeWelcome,
      stuck,
      updated,
      closeUpdated,
    }),
    [status, refresh, install, installing, installError, modalOpen, closeModal, welcomeVersion, closeWelcome, stuck, updated, closeUpdated],
  )
  return <UpdateContext.Provider value={value}>{children}</UpdateContext.Provider>
}

export const useUpdates = () => useContext(UpdateContext)
