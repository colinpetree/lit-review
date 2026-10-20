import { useEffect, useState } from 'react'

// How the Paper Datasets, Grading Prompts and Paper Evaluations lists are laid out. Kept per browser
// in localStorage, which can be missing or throw (private window, blocked site
// data), so every access is guarded and the default applies.
const KEY = 'lit-review.list-view'

export const VIEWS = ['table', 'card']
export const DEFAULT_VIEW = 'table'

export function getView() {
  try {
    const saved = localStorage.getItem(KEY)
    return VIEWS.includes(saved) ? saved : DEFAULT_VIEW
  } catch {
    return DEFAULT_VIEW
  }
}

// Current choice plus a setter, kept in step with other tabs and between the lists.
export function useView() {
  const [view, setViewState] = useState(getView)

  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === KEY) setViewState(getView())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const choose = (next) => {
    if (!VIEWS.includes(next)) return
    setViewState(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      // Storage unavailable: the choice still applies until reload.
    }
  }
  return [view, choose]
}
