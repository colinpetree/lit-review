import { useMemo } from 'react'
import Combobox from './Combobox'
import { MODELS_BY_PROVIDER } from '../lib/models'

// The providers that can be chosen for AI work: configured AND having models
// listed. `providers` also reports non-AI credentials (e.g. openalex), which
// must never show up as a model choice.
function aiProviders(providers) {
  return Object.keys(providers || {}).filter((p) => providers[p] && MODELS_BY_PROVIDER[p])
}

// Callers use hasConfiguredProvider(providers) to decide whether to show the
// picker or a "Configure API key" fallback instead.
export function hasConfiguredProvider(providers) {
  return aiProviders(providers).length > 0
}

export function defaultAiChoice(providers) {
  const provider = aiProviders(providers)[0]
  if (!provider) return null
  return { ai_api: provider, ai_model: MODELS_BY_PROVIDER[provider][0].id }
}

// Lists the models of every configured AI provider, grouped by provider once
// there is more than one. Renders nothing if none is configured.
export default function AiModelSelect({ providers, value, onChange }) {
  const configured = aiProviders(providers)

  const options = useMemo(
    () =>
      configured.flatMap((provider) =>
        MODELS_BY_PROVIDER[provider].map((m) => ({
          value: `${provider}::${m.id}`,
          label: m.label,
          group: provider,
        }))
      ),
    [configured.join(',')]
  )

  if (!configured.length) return null

  return (
    <Combobox
      options={options}
      value={`${value.ai_api}::${value.ai_model}`}
      onChange={(v) => {
        const [ai_api, ai_model] = v.split('::')
        onChange({ ai_api, ai_model })
      }}
      placeholder="Choose a model"
    />
  )
}
