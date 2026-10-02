// The paper databases a search can use, mirroring backend/search_sources.py
// (the backend's order is the order they are searched in; this one is the
// order they are listed, which follows the Paper Databases cards on the Settings
// page). `key` is the credential provider that must have a saved key (see
// Settings) before the source is offered; none means it works without one.
// `icon` is the source's logo.
import { ElsevierIcon, OpenAlexIcon, PubMedIcon, SemanticScholarIcon } from '../components/ProviderIcons'

export const PAPER_SOURCES = [
  { id: 'pubmed', label: 'PubMed', icon: PubMedIcon },
  { id: 'openalex', label: 'OpenAlex', icon: OpenAlexIcon },
  { id: 'elsevier', label: 'Elsevier (Scopus)', icon: ElsevierIcon, key: 'elsevier' },
  { id: 'semanticscholar', label: 'Semantic Scholar', icon: SemanticScholarIcon, key: 'semanticscholar' },
]

export const DEFAULT_SOURCES = ['openalex']

export function sourceLabel(id) {
  return PAPER_SOURCES.find((s) => s.id === id)?.label ?? id
}

export function sourceIcon(id) {
  return PAPER_SOURCES.find((s) => s.id === id)?.icon
}
