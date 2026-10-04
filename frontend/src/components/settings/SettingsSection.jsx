// A titled group of cards on a settings page.
export default function SettingsSection({ title, description, children }) {
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{title}</h2>
        {description ? <p className="mt-1 text-sm text-gray-600">{description}</p> : null}
      </div>
      <div className="flex flex-col gap-4">{children}</div>
    </div>
  )
}
