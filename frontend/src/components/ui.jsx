export function PageShell({ title, actions, children }) {
  return (
    <div className="max-w-3xl mx-auto px-4 py-10">
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
      <div className="mt-6">{children}</div>
    </div>
  )
}

export function Card({ className = '', children }) {
  return (
    <div className={`bg-white rounded-lg border border-gray-200 shadow-sm p-6 ${className}`}>
      {children}
    </div>
  )
}
