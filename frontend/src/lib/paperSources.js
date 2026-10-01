// The paper databases a search can use, mirroring backend/search_sources.py.
// `key` is the credential provider that must have a saved key (see Settings)
// before the source can be selected; none means it works without one. `icon` is
// the source's logo.
import { ElsevierIcon, OpenAlexIcon, SemanticScholarIcon } from '../components/ProviderIcons'

export const PAPER_SOURCES = [
  { id: 'openalex', label: 'OpenAlex', icon: OpenAlexIcon },
  // Not listed at all until a key is saved: keys are approved by hand and
  // revoked after 60 days without use, so most people won't have one.
  {
    id: 'semanticscholar',
    label: 'Semantic Scholar',
    icon: SemanticScholarIcon,
    key: 'semanticscholar',
    hiddenWithoutKey: true,
  },
  { id: 'elsevier', label: 'Elsevier (Scopus)', icon: ElsevierIcon, key: 'elsevier' },
]

export const DEFAULT_SOURCES = ['openalex']

export function sourceLabel(id) {
  return PAPER_SOURCES.find((s) => s.id === id)?.label ?? id
}

export function sourceIcon(id) {
  return PAPER_SOURCES.find((s) => s.id === id)?.icon
}
