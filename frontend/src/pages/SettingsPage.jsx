import { useEffect, useState } from 'react'
import { PageShell, Card } from '../components/ui'
import EditableCardHeader from '../components/EditableCardHeader'
import useSavedState from '../lib/useSavedState'

function ProviderKeyCard({
  provider,
  label,
  keyName: keyNameOverride,
  description,
  keyUrl,
  keyPlaceholder = 'API key...',
  hasKey,
  onSave,
  onDelete,
}) {
  const [input, setInput] = useState('')
  const [removing, setRemoving] = useState(false)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  const isDirty = removing || input.trim().length > 0
  // Named after the key's own type when the company has more than one kind.
  const keyName = keyNameOverride ?? `${label} API Key`
  const article = /^[aeiou]/i.test(keyName) ? 'an' : 'a'

  function cancel() {
    setInput('')
    setRemoving(false)
    setEditing(false)
    setError('')
  }

  function handleSave() {
    commit(async () => {
      if (removing) {
        await onDelete(provider)
      } else {
        await onSave(provider, input)
      }
      setInput('')
      setRemoving(false)
    })
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title={label}
        description={description}
        linkUrl={keyUrl}
        linkLabel={`Get ${article} ${keyName}`}
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={isDirty}
        onEdit={() => setEditing(true)}
        onCancel={cancel}
        onSave={handleSave}
      />

      {editing ? (
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium text-gray-700">{keyName}</label>
          <input
            type="password"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={removing}
            placeholder={hasKey ? '••••••••' : keyPlaceholder}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 w-full disabled:bg-gray-50 disabled:text-gray-400"
          />
          {hasKey && !removing && (
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-400">Currently set, enter a new value to replace it.</p>
              <button
                type="button"
                onClick={() => {
                  setRemoving(true)
                  setInput('')
                }}
                className="text-xs text-red-600 hover:underline"
              >
                Remove saved key
              </button>
            </div>
          )}
          {removing && (
            <p className="text-xs text-red-600">
              Key will be removed when you save.{' '}
              <button type="button" onClick={() => setRemoving(false)} className="underline">
                Undo
              </button>
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">{keyName}</p>
          {hasKey ? <p className="text-sm text-gray-900">••••••••</p> : <p className="text-sm text-gray-400">Not set</p>}
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}
    </Card>
  )
}

const AI_PROVIDERS = [
  {
    id: 'anthropic',
    label: 'Anthropic',
    description: 'Required. Used to turn your topic into search queries and to score papers against your criteria. Stored locally in an encrypted file on this machine and only sent to Anthropic.',
    keyUrl: 'https://console.anthropic.com/settings/keys',
    keyPlaceholder: 'sk-ant-...',
  },
]

const PAPER_DB_KEY_PROVIDERS = [
  {
    id: 'openalex',
    label: 'OpenAlex',
    description: 'Recommended, not required. OpenAlex is the main source searched on Discover Papers. Without a key, requests share a small daily limit with everyone on your network, which a university network can use up quickly. A free key gets its own private daily limit.',
    keyUrl: 'https://openalex.org/settings/api',
    keyPlaceholder: 'Paste your OpenAlex API key...',
  },
  // Elsevier and Springer Nature don't let OpenAlex redistribute their
  // abstracts, so the "Find missing abstracts" button on a data set uses their
  // own free APIs for those papers.
  {
    id: 'elsevier',
    label: 'Elsevier',
    description: 'Optional. Adds Elsevier (Scopus) as a search source on Discover Papers and looks up missing abstracts for Elsevier papers (DOIs starting 10.1016), which other sources often can’t provide. Free for non-commercial use. Stored locally and only sent to Elsevier.',
    keyUrl: 'https://dev.elsevier.com/',
    keyPlaceholder: 'Paste your Elsevier API key...',
  },
  {
    id: 'springernature',
    label: 'Springer Nature',
    keyName: 'Springer Nature Meta API Key',
    description: 'Optional. Used only to look up missing abstracts for Springer and Nature papers (DOIs starting 10.1007, 10.1038 and 10.1186), which other sources often can’t provide. Free plan, no institution needed. Stored locally and only sent to Springer Nature.',
    keyUrl: 'https://dev.springernature.com/',
    keyPlaceholder: 'Paste your Springer Nature API key...',
  },
  {
    id: 'semanticscholar',
    label: 'Semantic Scholar',
    description: 'Optional. Adds Semantic Scholar as a search source on Discover Papers (it only appears once a key is saved) and makes abstract lookup more reliable. Abstract lookup still tries it without a key, but the shared limit is often used up. Free, but approved by hand and revoked after 60 days without use.',
    keyUrl: 'https://www.semanticscholar.org/product/api#api-key-form',
    keyPlaceholder: 'Paste your Semantic Scholar API key...',
  },
]

function SettingsSection({ title, children }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{title}</h2>
      <div className="flex flex-col gap-4">{children}</div>
    </div>
  )
}

export default function SettingsPage() {
  const [keyStatus, setKeyStatus] = useState(null)

  const refreshKeys = () => {
    fetch('/api/settings/api-key')
      .then((res) => res.json())
      .then(setKeyStatus)
      .catch(() => setKeyStatus({}))
  }

  useEffect(refreshKeys, [])

  const saveKey = async (provider, apiKey) => {
    const res = await fetch('/api/settings/api-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`)
    refreshKeys()
  }

  const deleteKey = async (provider) => {
    await fetch('/api/settings/api-key', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    })
    refreshKeys()
  }

  return (
    <PageShell title="Settings">
      <div className="flex flex-col gap-8">
        <SettingsSection title="Paper Databases">
          {PAPER_DB_KEY_PROVIDERS.map((provider) => (
            <ProviderKeyCard
              key={provider.id}
              provider={provider.id}
              label={provider.label}
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

        <SettingsSection title="AI Integrations">
          {AI_PROVIDERS.map((provider) => (
            <ProviderKeyCard
              key={provider.id}
              provider={provider.id}
              label={provider.label}
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
