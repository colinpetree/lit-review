import { useLayoutEffect, useRef } from 'react'

// A textarea with no drag handle that grows to fit its content. `rows` sets
// the minimum height. Drop-in for <textarea> (extra props pass through).
export default function AutoGrowTextarea({ value, className = '', ...props }) {
  const ref = useRef(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => {
      const border = el.offsetHeight - el.clientHeight
      // Reset first so the field can also shrink when text is removed.
      el.style.height = 'auto'
      el.style.height = `${el.scrollHeight + border}px`
    }
    fit()
    // Wrapping changes with width, which changes the needed height.
    let lastWidth = el.offsetWidth
    const observer = new ResizeObserver(() => {
      if (el.offsetWidth !== lastWidth) {
        lastWidth = el.offsetWidth
        fit()
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [value])

  return <textarea ref={ref} value={value} className={`resize-none overflow-hidden ${className}`} {...props} />
}
