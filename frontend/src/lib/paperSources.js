// The paper databases a search can use, mirroring backend/search_sources.py.
// `key` is the credential provider that must have a saved key (see Settings)
// before the source can be selected; none means it works without one.
export const PAPER_SOURCES = [
  { id: 'openalex', label: 'OpenAlex' },
  // Not listed at all until a key is saved: keys are approved by hand and
  // revoked after 60 days without use, so most people won't have one.
  { id: 'semanticscholar', label: 'Semantic Scholar', key: 'semanticscholar', hiddenWithoutKey: true },
  { id: 'elsevier', label: 'Elsevier (Scopus)', key: 'elsevier' },
]

export const DEFAULT_SOURCES = ['openalex']

export function sourceLabel(id) {
  return PAPER_SOURCES.find((s) => s.id === id)?.label ?? id
}
