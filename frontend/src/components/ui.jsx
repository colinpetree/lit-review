import { Link } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'

export function PageShell({ title, actions, children }) {
  return (
    <div className="max-w-3xl mx-auto px-4 py-10">
      {title || actions ? (
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
          {actions ? <div className="shrink-0">{actions}</div> : null}
        </div>
      ) : null}
      <div className={title || actions ? 'mt-6' : ''}>{children}</div>
    </div>
  )
}

// "Back to ..." navigation link: gray, left chevron, no underline.
export function BackLink({ to, children }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700">
      <ChevronLeft size={16} />
      {children}
    </Link>
  )
}

export function Card({ className = '', children }) {
  return (
    <div className={`bg-white rounded-lg border border-gray-200 shadow-sm p-6 ${className}`}>
      {children}
    </div>
  )
}
