import { Link } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'

export function PageShell({ title, icon: Icon, description, actions, children }) {
  return (
    <div className="max-w-3xl mx-auto px-4 py-10">
      {title || actions ? (
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-3 text-2xl font-semibold text-gray-800">
              {Icon ? <Icon size={24} /> : null}
              {title}
            </h1>
            {description ? <p className="mt-2 text-sm text-gray-600">{description}</p> : null}
          </div>
          {actions ? <div className="shrink-0">{actions}</div> : null}
        </div>
      ) : null}
      <div className={title || actions ? 'mt-6' : ''}>{children}</div>
    </div>
  )
}

// "Back to ..." navigation link: gray, left chevron, no underline.
export function BackLink({ to, onClick, children }) {
  return (
    <Link to={to} onClick={onClick} className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
      <ChevronLeft size={16} />
      {children}
    </Link>
  )
}

// An inline link to another page, for pointing a new user at where to go next.
export function TextLink({ to, children }) {
  return (
    <Link
      to={to}
      className="text-blue-600 underline-offset-2 hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
    >
      {children}
    </Link>
  )
}

export function Card({ className = '', children }) {
  return (
    <div className={`bg-surface rounded-lg border border-gray-200 shadow-sm p-6 ${className}`}>
      {children}
    </div>
  )
}
