import { Check } from 'lucide-react'

// A styled checkbox with an optional label. The native input stays in the DOM
// (visually hidden) so keyboard, focus and form behavior are unchanged.
// `children` is the label content and may include icons or links.
export default function Checkbox({ checked, onChange, disabled = false, children, className = '' }) {
  return (
    <label
      className={`flex select-none items-center gap-2.5 text-sm ${
        disabled ? 'cursor-default text-gray-400' : 'cursor-pointer text-gray-700'
      } ${className}`}
    >
      <span className="relative inline-flex shrink-0">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange?.(e.target.checked)}
          className="peer absolute inset-0 m-0 h-full w-full cursor-[inherit] appearance-none rounded opacity-0"
        />
        <span
          className={`flex h-4 w-4 items-center justify-center rounded border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-blue-300 dark:peer-focus-visible:ring-blue-700 ${
            checked
              ? disabled
                ? 'border-blue-300 bg-blue-300 dark:border-blue-800 dark:bg-blue-800'
                : 'border-blue-600 bg-blue-600'
              : disabled
                ? 'border-gray-200 bg-gray-50'
                : 'border-gray-300 bg-surface'
          }`}
        >
          {checked ? <Check size={12} strokeWidth={3} className="text-white" /> : null}
        </span>
      </span>
      {children}
    </label>
  )
}
