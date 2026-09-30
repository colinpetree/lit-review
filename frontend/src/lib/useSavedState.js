import { useEffect, useRef, useState } from 'react'

// Edit/save lifecycle for an EditableCardHeader card: commit(action) runs the
// save, shows "Saving...", then leaves edit mode with a brief "Saved" state.
export default function useSavedState() {
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  // Guards every state update in commit() below against firing after
  // unmount (e.g. the user navigates away within the ~1-3s the "Saved"
  // confirmation is showing) - also clears the pending "hide Saved" timer
  // on unmount so it never fires at all in that case.
  const mountedRef = useRef(true)
  const savedTimerRef = useRef(null)

  useEffect(
    () => () => {
      mountedRef.current = false
      clearTimeout(savedTimerRef.current)
    },
    []
  )

  async function commit(action) {
    setSaving(true)
    setError('')
    try {
      await action()
      await new Promise((r) => setTimeout(r, 700))
      if (!mountedRef.current) return
      setSaved(true)
      setEditing(false)
      savedTimerRef.current = setTimeout(() => mountedRef.current && setSaved(false), 2500)
    } catch (err) {
      if (mountedRef.current) setError(err.message || 'Save failed')
    } finally {
      if (mountedRef.current) setSaving(false)
    }
  }

  return { editing, setEditing, saving, saved, error, setError, commit }
}
