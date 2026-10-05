import { useEffect, useState } from 'react'

// The side navs (the app's sidebar and the settings modal's list) show labels from Tailwind's
// lg breakpoint up; below it, only icons. Keep in step with the lg: classes in those navs.
const COLLAPSED_QUERY = '(max-width: 1023.98px)'

export default function useCollapsedNav() {
  const [collapsed, setCollapsed] = useState(() => window.matchMedia(COLLAPSED_QUERY).matches)
  useEffect(() => {
    const mql = window.matchMedia(COLLAPSED_QUERY)
    const onChange = (e) => setCollapsed(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])
  return collapsed
}
