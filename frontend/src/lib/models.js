// Mirrors backend/llm.py's PRICING_PER_MTOK keys - kept in sync by hand since
// there's no shared schema between the two. Only "anthropic" has a key-storage
// UI today; adding a provider here means adding its models under a new key.
export const MODELS_BY_PROVIDER = {
  anthropic: [
    { id: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
    { id: 'claude-sonnet-5', label: 'Claude Sonnet 5' },
    { id: 'claude-opus-5', label: 'Claude Opus 5' },
    { id: 'claude-fable-5-1', label: 'Claude Fable 5.1' },
  ],
}
