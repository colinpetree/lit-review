// What the Discover Papers form remembers between visits: the paper sources and
// the AI model from the last run. The topic and the year range are deliberately
// not remembered, since they're different every time. Kept in this browser's
// localStorage, which can be missing or throw (private window, blocked site
// data), so every access is guarded and the form just uses its defaults.
const STORAGE_KEY = 'lit-review.discover-settings'

export function loadDiscoverSettings() {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (!data || typeof data !== 'object') return {}
    const choice = data.aiChoice
    return {
      sources: Array.isArray(data.sources) ? data.sources.filter((s) => typeof s === 'string') : null,
      aiChoice:
        choice && typeof choice.ai_api === 'string' && typeof choice.ai_model === 'string'
          ? { ai_api: choice.ai_api, ai_model: choice.ai_model }
          : null,
    }
  } catch {
    return {}
  }
}

export function saveDiscoverSettings({ sources, aiChoice }) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ sources, aiChoice }))
  } catch {
    // Not remembering is fine.
  }
}
