import { useState, useRef, useEffect, useMemo } from 'react'
import { Calendar } from 'lucide-react'
import { DayPicker } from 'react-day-picker'

const DAY_PICKER_CLASSES = {
  months: 'relative',
  month_caption: 'flex justify-center items-center h-8 mb-2',
  caption_label: 'text-sm font-semibold text-gray-800',
  nav: 'absolute inset-x-0 top-0 flex justify-between',
  button_previous: 'h-8 w-8 flex items-center justify-center rounded text-gray-500 hover:bg-gray-100 transition-colors',
  button_next: 'h-8 w-8 flex items-center justify-center rounded text-gray-500 hover:bg-gray-100 transition-colors',
  month_grid: 'w-full',
  weekdays: 'flex',
  weekday: 'flex-1 text-center text-xs font-medium text-gray-400 pb-2',
  weeks: 'flex flex-col gap-0.5',
  week: 'flex',
  day: 'flex-1 flex justify-center',
  day_button: [
    'h-8 w-8 text-sm rounded transition-colors flex items-center justify-center cursor-pointer',
    'text-gray-700 hover:bg-gray-100',
    'data-[selected]:bg-gray-800 data-[selected]:text-white data-[selected]:hover:bg-gray-700 dark:data-[selected]:bg-gray-200 dark:data-[selected]:text-gray-900 dark:data-[selected]:hover:bg-gray-300',
    'data-[today]:font-semibold data-[today]:text-gray-800',
    'data-[outside]:text-gray-300 data-[outside]:hover:bg-transparent',
    'data-[disabled]:text-gray-200 data-[disabled]:hover:bg-transparent',
  ].join(' '),
  selected: '',
  today: '',
  outside: '',
  disabled: '',
  hidden: 'invisible',
  chevron: 'w-3.5 h-3.5 fill-gray-500',
}

// Date-only picker (text input + calendar popup), copied from the
// an earlier project's ui/DatePicker. value/onChange work in plain
// "YYYY-MM-DD". align="right" opens the calendar flush with the input's right
// edge, for pickers near the right side of a container.
export default function DatePicker({ value, onChange, onBlur, placeholder = 'YYYY-MM-DD', className = '', align = 'left', ariaLabel }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  useEffect(() => {
    if (!open) return
    function handleOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [open])

  const selectedDate = useMemo(() => {
    if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined
    const [y, m, d] = value.split('-').map(Number)
    return new Date(y, m - 1, d)
  }, [value])

  function handleDaySelect(date) {
    if (!date) {
      setOpen(false)
      return
    }
    const y = date.getFullYear()
    const m = String(date.getMonth() + 1).padStart(2, '0')
    const d = String(date.getDate()).padStart(2, '0')
    const newValue = `${y}-${m}-${d}`
    onChange(newValue)
    setOpen(false)
    onBlur?.(newValue)
  }

  return (
    <div className={`relative ${className}`} ref={containerRef}>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        onBlur={() => onBlur?.(value)}
        onClick={() => setOpen(true)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        data-open={open}
        className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-800 w-full pr-8 outline-none"
      />
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
      >
        <Calendar size={13} />
      </button>

      {open && (
        <div className={`absolute top-full ${align === 'right' ? 'right-0' : 'left-0'} z-50 mt-1 bg-surface border border-gray-200 rounded-lg shadow-lg p-3 w-[17rem]`}>
          <DayPicker mode="single" selected={selectedDate} onSelect={handleDaySelect} classNames={DAY_PICKER_CLASSES} />
        </div>
      )}
    </div>
  )
}
