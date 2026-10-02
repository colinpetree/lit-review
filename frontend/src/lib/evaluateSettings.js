// What the Evaluate Papers form remembers between visits: the AI model from the
// last run. Kept separately from Discover Papers' (lib/discoverSettings.js),
// since scoring papers often calls for a different model than writing search
// queries. The datasets and the criteria are deliberately not remembered. Kept in
// this browser's localStorage, which can be missing or throw (private window,
// blocked site data), so every access is guarded and the form just uses its default.
const STORAGE_KEY = 'lit-review.analyze-settings'

export function loadEvaluateAiChoice() {
  try {
    const choice = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')?.aiChoice
    return choice && typeof choice.ai_api === 'string' && typeof choice.ai_model === 'string'
      ? { ai_api: choice.ai_api, ai_model: choice.ai_model }
      : null
  } catch {
    return null
  }
}

export function saveEvaluateAiChoice(aiChoice) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ aiChoice }))
  } catch {
    // Not remembering is fine.
  }
}
