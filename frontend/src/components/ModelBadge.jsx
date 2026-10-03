import { PROVIDER_ICONS, PROVIDER_LABELS, modelName } from '../lib/models'

// An AI model as its provider's logo plus its name, with an optional estimated
// cost (costNote is shown as its tooltip). The color comes from the parent's
// text color (pass a text-* class).
export default function ModelBadge({ aiApi, aiModel, cost, costNote, className = '' }) {
  if (!aiModel) return null
  const Icon = PROVIDER_ICONS[aiApi]
  return (
    <span className={`flex items-center gap-2 ${className}`} title={PROVIDER_LABELS[aiApi]}>
      {Icon ? <Icon size={14} className="shrink-0" /> : null}
      {modelName(aiApi, aiModel)}
      {cost != null ? (
        <span className="text-gray-400" title={costNote}>
          · est. ${cost.toFixed(4)}
        </span>
      ) : null}
    </span>
  )
}
