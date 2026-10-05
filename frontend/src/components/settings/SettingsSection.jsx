// A titled group of cards inside a settings section.
export default function SettingsSection({ title, description, children }) {
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{title}</h3>
        {description ? <p className="mt-1 text-sm text-gray-600">{description}</p> : null}
      </div>
      <div className="flex flex-col gap-4">{children}</div>
    </div>
  )
}
