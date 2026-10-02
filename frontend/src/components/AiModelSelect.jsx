import { useMemo } from 'react'
import Combobox from './Combobox'
import { MODELS_BY_PROVIDER, PROVIDER_LABELS, providerIcon } from '../lib/models'

// The providers that can be chosen for AI work: configured AND having models
// listed. `providers` also reports non-AI credentials (e.g. openalex), which
// must never show up as a model choice. Listed in MODELS_BY_PROVIDER's order, not
// the order the server reports them in (which is arbitrary).
function aiProviders(providers) {
  return Object.keys(MODELS_BY_PROVIDER).filter((p) => providers?.[p])
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
        MODELS_BY_PROVIDER[provider].map((m, i, all) => ({
          value: `${provider}::${m.id}`,
          label: m.label,
          // Models are listed cheapest first, so position is the price tier.
          hint: '$'.repeat(i + 1),
          hintTitle: `Price tier ${i + 1} of ${all.length} for ${PROVIDER_LABELS[provider]}`,
          group: PROVIDER_LABELS[provider] || provider,
          // So typing a provider ("google", "groq", "anthropic") or a model id
          // ("gpt-oss-20b", "claude-haiku") finds it, not just the display name.
          keywords: `${provider} ${m.id.split('/').pop()}`,
          icon: providerIcon(provider),
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
      narrowScrollbar
    />
  )
}
