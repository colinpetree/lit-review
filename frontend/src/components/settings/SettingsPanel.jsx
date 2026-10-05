import { SETTINGS_NAV } from '../../lib/navItems'

// One section of the settings modal: its title (and the icon its link in the modal's list
// has) and intro, then the cards. The modal draws the divider between sections.
export default function SettingsPanel({ id, title, description, children }) {
  const Icon = SETTINGS_NAV.find((item) => item.id === id)?.icon
  return (
    <section id={`settings-${id}`} aria-labelledby={`settings-${id}-title`}>
      <h2 id={`settings-${id}-title`} className="flex items-center gap-3 text-2xl font-semibold text-gray-800">
        {Icon ? <Icon size={24} /> : null}
        {title}
      </h2>
      {description ? <p className="mt-2 text-sm text-gray-600">{description}</p> : null}
      <div className="mt-6">{children}</div>
    </section>
  )
}
