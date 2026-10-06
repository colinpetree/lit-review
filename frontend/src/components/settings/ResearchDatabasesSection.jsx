import SettingsPanel from './SettingsPanel'
import useApiKeys from '../../lib/useApiKeys'
import ProviderKeyCard from './ProviderKeyCard'
import PubMedCard from './PubMedCard'
import SettingsSection from './SettingsSection'
import KeyStoreNotice from './KeyStoreNotice'
import { ElsevierIcon, OpenAlexIcon, SemanticScholarIcon, SpringerNatureIcon } from '../ProviderIcons'

const PAPER_DB_KEY_PROVIDERS = [
  {
    id: 'openalex',
    label: 'OpenAlex',
    icon: OpenAlexIcon,
    description: 'Recommended. Without a key, the shared daily limit is easily reached. A free key gives you your own limit.',
    keyUrl: 'https://openalex.org/settings/api',
    keyPlaceholder: 'Paste your OpenAlex API key...',
  },
  // Elsevier and Springer Nature don't let OpenAlex redistribute their
  // abstracts, so the "Find missing abstracts" button on a dataset uses their
  // own free APIs for those papers. Springer Nature publishes only a PNG
  // favicon, so its icon is a full-color image.
  {
    id: 'elsevier',
    label: 'Elsevier (Scopus)',
    icon: ElsevierIcon,
    description: 'Optional. Adds Elsevier (Scopus) as a search source and looks up missing abstracts for Elsevier papers. Free for non-commercial use.',
    keyUrl: 'https://dev.elsevier.com/',
    keyPlaceholder: 'Paste your Elsevier API key...',
  },
  {
    id: 'springernature',
    label: 'Springer Nature',
    icon: SpringerNatureIcon,
    keyName: 'Springer Nature Meta API Key',
    description: 'Optional. Looks up missing abstracts for Springer and Nature papers. Free, no institution needed.',
    keyUrl: 'https://dev.springernature.com/',
    keyPlaceholder: 'Paste your Springer Nature API key...',
  },
  {
    id: 'semanticscholar',
    label: 'Semantic Scholar',
    icon: SemanticScholarIcon,
    description: 'Optional. Adds Semantic Scholar as a search source and makes abstract lookup more reliable. Free, but approved by hand and revoked after 60 days without use.',
    keyUrl: 'https://www.semanticscholar.org/product/api#api-key-form',
    keyPlaceholder: 'Paste your Semantic Scholar API key...',
  },
]

export default function ResearchDatabasesSection() {
  const { keyStatus, saveKey, deleteKey } = useApiKeys()

  return (
    <SettingsPanel
      title="Research Databases"
      id="databases"
      description="Databases Lit Review searches for papers and missing abstracts. PubMed always works without a key. Add a free key for each of the others to avoid rate limits and find more papers."
    >
      <div className="flex flex-col gap-8">
        {keyStatus?.store_error && <KeyStoreNotice />}

        <SettingsSection title="Databases">
          <PubMedCard />
          {PAPER_DB_KEY_PROVIDERS.map((provider) => (
            <ProviderKeyCard
              key={provider.id}
              provider={provider.id}
              label={provider.label}
              icon={provider.icon}
              keyName={provider.keyName}
              description={provider.description}
              keyUrl={provider.keyUrl}
              keyPlaceholder={provider.keyPlaceholder}
              hasKey={Boolean(keyStatus?.[provider.id])}
              onSave={saveKey}
              onDelete={deleteKey}
            />
          ))}
        </SettingsSection>
      </div>
    </SettingsPanel>
  )
}
