import { useEffect, useState } from 'react'
import { CircleDollarSign, Database, Monitor, Moon, Sun } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageShell, Card } from '../components/ui'
import { navIcon } from '../lib/navItems'
import { fetchJson, postJson } from '../lib/api'
import { useTheme } from '../lib/theme'
import Combobox from '../components/Combobox'
import EditableCardHeader from '../components/EditableCardHeader'
import Toggle from '../components/Toggle'
import useSavedState from '../lib/useSavedState'
import { usePubMedEnabled } from '../lib/pubmedSetting'
import ConfirmModal from '../components/ConfirmModal'
import { downloadBackup, restoreBackup } from '../lib/dataFiles'
import { DEFAULT_THRESHOLD_TEXT, formatUsd, parseThreshold, useSpendThresholdText } from '../lib/spendSetting'
import {
  AnthropicIcon,
  ElsevierIcon,
  GeminiIcon,
  OpenAIIcon,
  OpenAlexIcon,
  PubMedIcon,
  SemanticScholarIcon,
  SpringerNatureIcon,
} from '../components/ProviderIcons'

// Stands in for a saved key (the real value is never sent to the browser), long
// enough that the field looks filled.
const MASKED_KEY = '•'.repeat(48)

function ProviderKeyCard({
  provider,
  label,
  icon,
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
        icon={icon}
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
            placeholder={hasKey ? MASKED_KEY : keyPlaceholder}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-800 w-full disabled:bg-gray-50 disabled:text-gray-400"
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
                className="text-xs text-red-600 dark:text-red-400 hover:underline"
              >
                Remove saved key
              </button>
            </div>
          )}
          {removing && (
            <p className="text-xs text-red-600 dark:text-red-400">
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
          {hasKey ? <p className="truncate text-sm text-gray-800">{MASKED_KEY}</p> : <p className="text-sm text-gray-400">Not set</p>}
        </div>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}

// PubMed needs no key, so its card is an on/off switch for offering it on
// Discover Papers (on by default), with the same Edit/Save flow as the key cards.
function PubMedCard() {
  const [enabled, setEnabled] = usePubMedEnabled()
  const [draft, setDraft] = useState(enabled)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  function startEditing() {
    setDraft(enabled)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="PubMed"
        icon={PubMedIcon}
        description="Biomedical, medical and health literature from the US National Library of Medicine. Free, and no key is needed. Turn it off if you don’t work in medicine or health and don’t want it listed as a source on Discover Papers."
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={draft !== enabled}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={() => commit(async () => setEnabled(draft))}
      />

      {editing ? (
        <Toggle label="Offer PubMed as a paper source" checked={draft} onChange={setDraft} />
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">Status</p>
          <p className="text-sm">
            {enabled ? (
              <span className="font-medium text-[#30cf43]">Enabled</span>
            ) : (
              <span className="text-gray-400">Disabled</span>
            )}
          </p>
        </div>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}

// How much a run may cost before Evaluate Papers asks first. A per-browser setting like
// PubMed's, with the same Edit/Save flow as the key cards.
function SpendCard() {
  const [text, setText] = useSpendThresholdText()
  const [draft, setDraft] = useState(text)
  const { editing, setEditing, saving, saved, error, setError, commit } = useSavedState()

  // A damaged stored value counts as the default (as getSpendThreshold does), not as blank.
  const parsed = parseThreshold(text)
  const threshold = parsed === undefined ? parseThreshold(DEFAULT_THRESHOLD_TEXT) : parsed
  const draftValue = parseThreshold(draft)

  function startEditing() {
    setDraft(text)
    setEditing(true)
  }

  function cancel() {
    setEditing(false)
    setError('')
  }

  return (
    <Card className="flex flex-col gap-5">
      <EditableCardHeader
        title="Spending"
        icon={CircleDollarSign}
        description="Before a run starts, Evaluate Papers shows about what it will cost. It asks you to confirm when that is more than this amount, and the run then stops at about the amount you confirmed, so a run cannot cost far more than you expected. Enter 0 to be asked before every run, or leave it blank to never be asked (runs then have no limit)."
        editing={editing}
        saving={saving}
        saved={saved}
        isDirty={draft.trim() !== text.trim() && draftValue !== undefined}
        onEdit={startEditing}
        onCancel={cancel}
        onSave={() =>
          commit(async () => {
            if (draftValue === undefined) throw new Error('Enter an amount in dollars, such as 1.00, or leave it blank.')
            setText(draft.trim())
          })
        }
      />

      {editing ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor="spend-threshold" className="text-sm font-medium text-gray-700">
            Ask before spending more than (US dollars)
          </label>
          <input
            id="spend-threshold"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            inputMode="decimal"
            placeholder="No limit"
            className="w-40 rounded-md border border-gray-300 px-3 py-2 text-sm"
          />
          {draftValue === undefined ? (
            <p className="text-xs text-red-500 dark:text-red-400">Enter an amount in dollars, such as 1.00.</p>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <p className="text-sm font-medium text-gray-700">Ask before spending more than</p>
          <p className="text-sm text-gray-800">
            {threshold === null
              ? 'Never ask'
              : threshold === 0
                ? 'Ask before every run'
                : formatUsd(threshold)}
          </p>
        </div>
      )}

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
    </Card>
  )
}

// Backing up and restoring everything the app has stored (not the API keys), and the way
// to the trash. A restore replaces all current data, so it is confirmed first and the
// replaced data is kept by the server as a file.
function DataCard() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [picked, setPicked] = useState(null) // the file chosen to restore, awaiting confirmation
  const [restored, setRestored] = useState(null) // the server's answer after a restore

  async function backup() {
    setError(null)
    setBusy(true)
    try {
      await downloadBackup()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const buttonClass =
    'rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50'

  return (
    <Card className="flex flex-col gap-5">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-800 [--icon-nudge:-1px]">
        <Database size={18} className="shrink-0" />
        Backup and restore
      </h2>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Backup</p>
        <p className="text-xs text-gray-400">
          One file holding every dataset, paper, result run and prompt, and what you have spent. Your API keys are not
          included: they stay on this computer and are never backed up.
        </p>
        <button type="button" onClick={backup} disabled={busy} className={`${buttonClass} self-start`}>
          {busy ? 'Preparing…' : 'Download backup'}
        </button>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Restore</p>
        <p className="text-xs text-gray-400">
          Replaces everything now in the app with what is in a backup file. Your current data is first kept as a
          file in the app's data folder, so a restore can be undone.
        </p>
        <label className={`${buttonClass} cursor-pointer self-start`}>
          Restore from backup…
          <input
            type="file"
            accept=".db,application/octet-stream"
            className="sr-only"
            onChange={(e) => {
              setError(null)
              setRestored(null)
              setPicked(e.target.files?.[0] ?? null)
              // Choosing the same file again later must still fire a change.
              e.target.value = ''
            }}
          />
        </label>
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium text-gray-700">Deleted items</p>
        <p className="text-xs text-gray-400">
          Datasets and prompts you delete are kept, hidden from the rest of the app, until you remove them for good.
          Bring one back, or delete it permanently.
        </p>
        <Link
          to="/settings/trash"
          className="self-start text-sm text-blue-600 underline-offset-2 hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
        >
          View or restore deleted items
        </Link>
      </div>

      {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}
      {restored ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-gray-800">{restored.message}</p>
          <p className="text-sm text-gray-600">
            Any other Lit Review tab or window is still showing the old data: reload it.
          </p>
          <button type="button" onClick={() => window.location.reload()} className={`${buttonClass} self-start`}>
            Reload this page
          </button>
        </div>
      ) : null}

      {picked ? (
        <ConfirmModal
          title="Replace all your data with this backup?"
          message={`Everything now in Lit Review (datasets, papers, results, prompts and spending history) will be replaced by the contents of "${picked.name}". Your current data is kept as a file in the app's data folder first. Nothing else can be done in the app while it is restored. Your API keys are not affected.`}
          confirmLabel="Replace my data"
          busyLabel="Restoring..."
          danger
          onConfirm={async () => {
            setRestored(await restoreBackup(picked))
          }}
          onClose={() => setPicked(null)}
        />
      ) : null}
    </Card>
  )
}

const AI_PROVIDERS = [
  {
    id: 'anthropic',
    label: 'Anthropic',
    icon: AnthropicIcon,
    description: 'Claude models. Used to turn your topic into search queries and to score papers against your criteria. At least one AI integration is required. Stored locally in an encrypted file on this machine and only sent to Anthropic.',
    keyUrl: 'https://console.anthropic.com/settings/keys',
    keyPlaceholder: 'sk-ant-...',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    icon: OpenAIIcon,
    description: 'GPT models, for the same query and scoring work as the other AI integrations. Stored locally in an encrypted file on this machine and only sent to OpenAI.',
    keyUrl: 'https://platform.openai.com/api-keys',
    keyPlaceholder: 'sk-...',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    icon: GeminiIcon,
    description: 'Gemini models, for the same query and scoring work as the other AI integrations. Has a free tier. Stored locally in an encrypted file on this machine and only sent to Google.',
    keyUrl: 'https://aistudio.google.com/apikey',
    keyPlaceholder: 'AIza...',
  },
]

const PAPER_DB_KEY_PROVIDERS = [
  {
    id: 'openalex',
    label: 'OpenAlex',
    icon: OpenAlexIcon,
    description: 'Recommended, not required. OpenAlex is the main source searched on Discover Papers. Without a key, requests share a small daily limit with everyone on your network, which a university network can use up quickly. A free key gets its own private daily limit.',
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
    description: 'Optional. Adds Elsevier (Scopus) as a search source on Discover Papers and looks up missing abstracts for Elsevier papers (DOIs starting 10.1016), which other sources often can’t provide. Free for non-commercial use. Stored locally and only sent to Elsevier.',
    keyUrl: 'https://dev.elsevier.com/',
    keyPlaceholder: 'Paste your Elsevier API key...',
  },
  {
    id: 'springernature',
    label: 'Springer Nature',
    icon: SpringerNatureIcon,
    keyName: 'Springer Nature Meta API Key',
    description: 'Optional. Used only to look up missing abstracts for Springer and Nature papers (DOIs starting 10.1007, 10.1038 and 10.1186), which other sources often can’t provide. Free plan, no institution needed. Stored locally and only sent to Springer Nature.',
    keyUrl: 'https://dev.springernature.com/',
    keyPlaceholder: 'Paste your Springer Nature API key...',
  },
  {
    id: 'semanticscholar',
    label: 'Semantic Scholar',
    icon: SemanticScholarIcon,
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

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

export default function SettingsPage() {
  const [theme, setTheme] = useTheme()
  const [keyStatus, setKeyStatus] = useState(null)

  const refreshKeys = () => {
    fetchJson('/api/settings/api-key')
      .then(setKeyStatus)
      .catch(() => setKeyStatus({}))
  }

  useEffect(refreshKeys, [])

  const saveKey = async (provider, apiKey) => {
    await postJson('/api/settings/api-key', { provider, api_key: apiKey })
    refreshKeys()
  }

  const deleteKey = async (provider) => {
    await fetchJson('/api/settings/api-key', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    })
    refreshKeys()
  }

  return (
    <PageShell
      title="Settings"
      icon={navIcon('/settings')}
      description="Install API Keys for paper databases and AI platforms. Minimum is OpenAlex and one AI provider. More paper databases gives you more papers in your datasets and cross-check each other to fill in missing abstracts. More AI providers just gives you more AI model options to choose from."
    >
      <div className="flex flex-col gap-8">
        {keyStatus?.store_error && (
          <p
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/20 dark:text-red-300"
          >
            Your saved API keys could not be read, so they are shown as missing. A copy of the
            unreadable file is kept in the app's settings folder. Saving a key again starts a fresh
            store; you will need to enter each key again.
          </p>
        )}
        <SettingsSection title="Theme">
          <div className="max-w-xs">
            <Combobox options={THEME_OPTIONS} value={theme} onChange={setTheme} placeholder="Theme" />
          </div>
        </SettingsSection>

        <SettingsSection title="Spending">
          <SpendCard />
        </SettingsSection>

        <SettingsSection title="Your data">
          <DataCard />
        </SettingsSection>

        <SettingsSection title="Paper Databases">
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

        <SettingsSection title="AI Integrations">
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
    </PageShell>
  )
}
