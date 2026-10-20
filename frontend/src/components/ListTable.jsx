import { Children, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Tooltip } from './ui/Tooltip'

// Resting the pointer this close (px) to the table's left or right edge scrolls it that way, once
// it has stayed there EDGE_DWELL_MS (so passing through, or reaching for the first column, does
// not), at up to EDGE_MAX_SPEED px per frame (reached right at the edge).
const EDGE_ZONE = 48
const EDGE_DWELL_MS = 350
const EDGE_MAX_SPEED = 8

// Scrolls `boxRef` sideways while the pointer rests near its left or right edge over the table
// (`tableRef`), for a mouse with no sideways wheel. Nothing is drawn. Not while a row menu's
// popover is under the pointer, and it stops at either end of the table.
function useEdgeScroll(boxRef, tableRef) {
  const speed = useRef(0)
  const frame = useRef(0)
  const dwell = useRef(0)

  const step = () => {
    const box = boxRef.current
    if (!box || !speed.current) {
      frame.current = 0
      return
    }
    const before = box.scrollLeft
    box.scrollLeft += speed.current
    frame.current = box.scrollLeft === before ? 0 : requestAnimationFrame(step)
  }

  const stop = () => {
    speed.current = 0
    clearTimeout(dwell.current)
    dwell.current = 0
    cancelAnimationFrame(frame.current)
    frame.current = 0
  }

  useEffect(() => stop, [])

  const onMouseMove = (e) => {
    const box = boxRef.current
    const table = tableRef.current
    if (!box || !table || box.scrollWidth <= box.clientWidth || e.target.closest('[role="menu"]')) return stop()
    const area = box.getBoundingClientRect()
    const rows = table.getBoundingClientRect()
    if (e.clientY < rows.top || e.clientY > rows.bottom) return stop()
    const fromLeft = e.clientX - area.left
    const fromRight = area.right - e.clientX
    let next = 0
    if (fromRight < EDGE_ZONE && box.scrollLeft + box.clientWidth < box.scrollWidth - 1) {
      next = Math.ceil(EDGE_MAX_SPEED * (1 - Math.max(fromRight, 0) / EDGE_ZONE))
    } else if (fromLeft < EDGE_ZONE && box.scrollLeft > 0) {
      next = -Math.ceil(EDGE_MAX_SPEED * (1 - Math.max(fromLeft, 0) / EDGE_ZONE))
    }
    if (!next) return stop()
    const waiting = !frame.current && !dwell.current
    speed.current = next
    if (waiting) {
      dwell.current = setTimeout(() => {
        dwell.current = 0
        if (speed.current) frame.current = requestAnimationFrame(step)
      }, EDGE_DWELL_MS)
    }
  }

  return { onMouseMove, onMouseLeave: stop }
}

// The table view of a list page. A page makes one module-level component from `columns`
// (`[{ label, className }]`, where `className` is applied to the header and every cell of
// that column) and hands it to InfiniteList as `as`, so InfiniteList's rows land in the body
// and its "Show more" button sits under the table. Nothing is drawn while there are no rows
// (the page says why). Every column is always shown on one line per row; a table wider than
// the page scrolls sideways (wheel, arrow keys once focused, or resting the pointer near either
// edge). Row menus float over the page (MoreMenu `floating`), so the scroll box never has to
// make room for them. Long text is cut with an ellipsis (the full text is the tooltip).
export function DataTable({ columns, className, children }) {
  const boxRef = useRef(null)
  const tableRef = useRef(null)
  const edgeScroll = useEdgeScroll(boxRef, tableRef)
  if (Children.count(children) === 0) return null

  return (
    // Focusable, so the arrow keys scroll it sideways too. The bottom padding keeps the scrollbar
    // a little below the table (and its shadow unclipped) instead of against its rounded corners.
    <div
      ref={boxRef}
      {...edgeScroll}
      tabIndex={0}
      aria-label="Table, scrolls sideways"
      className="table-scroll overflow-x-auto rounded-lg pb-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
    >
      <table
        ref={tableRef}
        className={`w-max min-w-full whitespace-nowrap border-separate border-spacing-0 rounded-lg border border-gray-200 bg-surface text-left shadow-sm [&_tbody_tr:last-child_td:first-child]:rounded-bl-[7px] [&_tbody_tr:last-child_td:last-child]:rounded-br-[7px] ${className ?? ''}`}
      >
        <thead>
          <tr>
            {columns.map((c, i) => (
              <th
                key={c.label || i}
                scope="col"
                className={`px-3 py-2.5 text-xs font-medium uppercase tracking-wide text-gray-500 ${c.className ?? ''}`}
              >
                {c.label ? c.label : <span className="sr-only">Actions</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

// One row. Clicking anywhere on it opens `to`, except on a link or button inside it (the
// name link handles itself, and the menu must not navigate).
export function ListRow({ to, children }) {
  const navigate = useNavigate()
  return (
    <tr
      onClick={(e) => {
        if (e.target.closest('a, button')) return
        navigate(to)
      }}
      className="group cursor-pointer"
    >
      {children}
    </tr>
  )
}

// A body cell. `column.className` is passed so it matches its header.
export function Cell({ column, className = '', children }) {
  // The hover color is on the cells, not the row: a row's background ignores the table's rounded
  // corners, so on the last row it showed square corners past them. The last row's corner cells are
  // rounded to match instead (DataTable).
  return (
    <td className={`border-t border-gray-200 px-3 py-1.5 align-middle text-sm group-hover:bg-gray-50 ${column.className ?? ''} ${className}`}>
      {children}
    </td>
  )
}

// Long text cut to one line, with the whole of it in the app's tooltip (wrapped, since it can be long).
export function TruncatedText({ text, className = '' }) {
  return (
    <Tooltip content={text ? <span className="block max-w-sm whitespace-normal">{text}</span> : null}>
      <p className={`truncate ${className}`}>{text}</p>
    </Tooltip>
  )
}

// The cell that holds a row menu. The menu's modals render inside it, and a click in a
// modal bubbles up the React tree, so it must not reach the row.
export function MenuCell({ column, children }) {
  return (
    <Cell column={column} className="text-right">
      <div onClick={(e) => e.stopPropagation()} className="flex justify-end">
        {children}
      </div>
    </Cell>
  )
}
