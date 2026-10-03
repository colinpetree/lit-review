import { useSyncExternalStore } from 'react'
import { isNotConnected, subscribeNotConnected } from './session'

// True while the app is refusing this browser (see lib/session.js).
export default function useNotConnected() {
  return useSyncExternalStore(subscribeNotConnected, isNotConnected)
}
