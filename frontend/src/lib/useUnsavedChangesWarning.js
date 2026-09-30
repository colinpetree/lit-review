import { useEffect } from 'react'

// While `active`, closing or reloading the tab shows the browser's own "leave
// site?" confirmation. This only covers the tab/browser: the app's own links
// navigate without it.
export default function useUnsavedChangesWarning(active) {
  useEffect(() => {
    if (!active) return
    const warn = (e) => {
      e.preventDefault()
      // Some browsers only show the prompt when returnValue is set.
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [active])
}
