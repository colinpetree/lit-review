import { useEffect, useRef, useState } from 'react'
import { PAGE_SIZE, shownCount, showMore } from '../lib/paging'

// Renders `items` one page at a time and adds the next page when the user scrolls near
// the end. Only what is drawn is paged: the list handed in is already filtered and
// sorted, so counts, filters and exports still see every item. `resetKey` changes
// whenever the list is a different one (another filter, sort or record), which goes
// back to the first page.
export default function InfiniteList({ items, renderItem, resetKey = '', as: Tag = 'ul', className }) {
  const [state, setState] = useState({ key: resetKey, count: PAGE_SIZE })
  const count = shownCount(state, resetKey)
  const hasMore = items.length > count
  const sentinelRef = useRef(null)

  const loadMore = () => setState((prev) => showMore(prev, resetKey))

  // A new observer reports the sentinel's position as soon as it is made, so a page
  // that still ends inside the window goes straight on to the next one.
  useEffect(() => {
    const node = sentinelRef.current
    if (!hasMore || !node || typeof IntersectionObserver === 'undefined') return
    // The app scrolls inside a container, not the window, and a root margin only reaches
    // the edge of the root, so the nearest scrolling ancestor is the root.
    let root = node.parentElement
    while (root && !/auto|scroll/.test(getComputedStyle(root).overflowY)) root = root.parentElement
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadMore()
      },
      { root, rootMargin: '400px 0px' }
    )
    observer.observe(node)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMore, count, resetKey])

  return (
    <>
      <Tag className={className}>{items.slice(0, count).map(renderItem)}</Tag>
      {hasMore ? (
        <div ref={sentinelRef} className="mt-4 flex justify-center">
          <button
            type="button"
            onClick={loadMore}
            className="text-sm text-blue-600 underline-offset-2 hover:underline dark:text-blue-400"
          >
            Showing {count.toLocaleString()} of {items.length.toLocaleString()}. Show more
          </button>
        </div>
      ) : null}
    </>
  )
}
