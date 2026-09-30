import { MODELS_BY_PROVIDER } from '../lib/models'

// Lists every provider `providers` reports as configured, grouped by
// provider so a future non-Anthropic provider just adds another optgroup.
// Renders nothing if no provider is configured - callers use
// hasConfiguredProvider(providers) to decide whether to show this or a
// "Configure API key" fallback instead.
export function hasConfiguredProvider(providers) {
  return Boolean(providers) && Object.values(providers).some(Boolean)
}

export function defaultAiChoice(providers) {
  const provider = Object.keys(providers || {}).find((p) => providers[p])
  if (!provider) return null
  return { ai_api: provider, ai_model: MODELS_BY_PROVIDER[provider][0].id }
}

export default function AiModelSelect({ providers, value, onChange }) {
  const configured = Object.keys(providers || {}).filter((p) => providers[p])
  if (!configured.length) return null

  return (
    <select
      value={`${value.ai_api}::${value.ai_model}`}
      onChange={(e) => {
        const [ai_api, ai_model] = e.target.value.split('::')
        onChange({ ai_api, ai_model })
      }}
      className="rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
    >
      {configured.map((provider) => (
        <optgroup key={provider} label={provider}>
          {(MODELS_BY_PROVIDER[provider] || []).map((m) => (
            <option key={m.id} value={`${provider}::${m.id}`}>
              {m.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}
