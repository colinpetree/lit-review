// Mirrors the model ids in backend/llm.py's MODELS (per provider) - kept in
// sync by hand since there's no shared schema between the two. Adding a
// provider or model here also means adding it to the backend, and a key card
// for the provider in SettingsPage.jsx.
import { AnthropicIcon, GeminiIcon, OpenAIIcon } from '../components/ProviderIcons'

export const PROVIDER_LABELS = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Google Gemini',
}

// Each provider's models are listed cheapest first: the model picker shows the
// position as a price tier ("$" for the first, "$$" for the second, and so on).
export const MODELS_BY_PROVIDER = {
  anthropic: [
    { id: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
    { id: 'claude-sonnet-5', label: 'Claude Sonnet 5' },
    { id: 'claude-opus-5', label: 'Claude Opus 5' },
  ],
  openai: [
    { id: 'gpt-6-luna', label: 'GPT-6 Luna' },
    { id: 'gpt-6.1-sol', label: 'GPT-6.1 Sol' },
    { id: 'gpt-6-astra', label: 'GPT-6 Astra' },
  ],
  gemini: [
    { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite' },
    { id: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
    { id: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro (preview)' },
  ],
}

export const PROVIDER_ICONS = {
  anthropic: AnthropicIcon,
  openai: OpenAIIcon,
  gemini: GeminiIcon,
}

export function providerIcon(aiApi) {
  return PROVIDER_ICONS[aiApi]
}

// Just the model's display name ("Claude Haiku 4.5"), for places where the
// provider's logo already shows who makes it.
export function modelName(aiApi, aiModel) {
  return MODELS_BY_PROVIDER[aiApi]?.find((m) => m.id === aiModel)?.label ?? aiModel
}
