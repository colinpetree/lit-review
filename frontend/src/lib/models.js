// Mirrors the model ids in backend/llm.py's MODELS (per provider) - kept in
// sync by hand since there's no shared schema between the two. Adding a
// provider or model here also means adding it to the backend, and a key card
// for the provider in SettingsPage.jsx.
export const PROVIDER_LABELS = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Google Gemini',
  groq: 'Groq',
}

export const MODELS_BY_PROVIDER = {
  anthropic: [
    { id: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
    { id: 'claude-sonnet-5', label: 'Claude Sonnet 5' },
    { id: 'claude-opus-5', label: 'Claude Opus 5' },
    { id: 'claude-fable-5-1', label: 'Claude Fable 5.1' },
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
  groq: [
    { id: 'openai/gpt-oss-20b', label: 'GPT-OSS 20B' },
    { id: 'openai/gpt-oss-120b', label: 'GPT-OSS 120B' },
  ],
}

// "Model name (Provider)" for a run's stored ai_api/ai_model, falling back to
// the raw id for a model no longer listed.
export function modelLabel(aiApi, aiModel) {
  const model = MODELS_BY_PROVIDER[aiApi]?.find((m) => m.id === aiModel)
  const provider = PROVIDER_LABELS[aiApi]
  const name = model ? model.label : aiModel
  return provider ? `${name} (${provider})` : name
}
