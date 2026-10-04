import { PageShell } from '../../components/ui'
import { navIcon } from '../../lib/navItems'
import useApiKeys from '../../lib/useApiKeys'
import ProviderKeyCard from '../../components/settings/ProviderKeyCard'
import PubMedCard from '../../components/settings/PubMedCard'
import SettingsSection from '../../components/settings/SettingsSection'
import KeyStoreNotice from '../../components/settings/KeyStoreNotice'
import { ElsevierIcon, OpenAlexIcon, SemanticScholarIcon, SpringerNatureIcon } from '../../components/ProviderIcons'

const PAPER_DB_KEY_PROVIDERS = [
  {
    id: 'openalex',
    label: 'OpenAlex',
    icon: OpenAlexIcon,
    description: 'Recommended, not required. The main source for Discover Papers. A free key gives you your own daily limit instead of sharing one with your network.',
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

export default function ResearchDatabasesPage() {
  const { keyStatus, saveKey, deleteKey } = useApiKeys()

  return (
    <PageShell
      title="Research Databases"
      icon={navIcon('/settings/databases')}
      description="Where Lit Review searches for papers and looks up missing abstracts. OpenAlex is the main one, and a free key is recommended. More databases find more papers."
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
    </PageShell>
  )
}
