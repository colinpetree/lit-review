import SettingsPanel from './SettingsPanel'
import DataCard from './DataCard'

export default function YourDataSection() {
  return (
    <SettingsPanel
      title="Your Data"
      id="data"
      description="Your datasets, prompts and results are stored on this computer. Back them up, restore them, or bring back deleted items. API keys are not included in backups."
    >
      <DataCard />
    </SettingsPanel>
  )
}
