import SettingsPanel from './SettingsPanel'
import useApiKeys from '../../lib/useApiKeys'
import ProviderKeyCard from './ProviderKeyCard'
import SettingsSection from './SettingsSection'
import SpendCard from './SpendCard'
import KeyStoreNotice from './KeyStoreNotice'
import { AnthropicIcon, GeminiIcon, OpenAIIcon } from '../ProviderIcons'
import { modelNameList } from '../../lib/models'

const AI_PROVIDERS = [
  {
    id: 'anthropic',
    label: 'Anthropic',
    icon: AnthropicIcon,
    description: `Adds Claude models: ${modelNameList('anthropic')}.`,
    keyUrl: 'https://console.anthropic.com/settings/keys',
    keyPlaceholder: 'sk-ant-...',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    icon: OpenAIIcon,
    description: `Adds GPT models: ${modelNameList('openai')}.`,
    keyUrl: 'https://platform.openai.com/api-keys',
    keyPlaceholder: 'sk-...',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    icon: GeminiIcon,
    description: `Adds Gemini models: ${modelNameList('gemini')}.`,
    keyUrl: 'https://aistudio.google.com/apikey',
    keyPlaceholder: 'AIza...',
  },
]

export default function AiIntegrationsSection() {
  const { keyStatus, saveKey, deleteKey } = useApiKeys()

  return (
    <SettingsPanel
      title="AI Integrations"
      id="ai"
      description="Lit Review uses AI to write search queries and to score papers. Add a key from at least one company below. They bill you directly for what you use."
    >
      <div className="flex flex-col gap-8">
        {keyStatus?.store_error && <KeyStoreNotice />}

        <SettingsSection
          title="Spending"
          description="Lit Review shows a cost estimate before each scoring run. Choose when it should ask first."
        >
          <SpendCard />
        </SettingsSection>

        <SettingsSection
          title="AI providers"
          description="At least one is required. Keys stay on this computer and are only sent to their own company."
        >
          {AI_PROVIDERS.map((provider) => (
            <ProviderKeyCard
              key={provider.id}
              provider={provider.id}
              label={provider.label}
              icon={provider.icon}
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
