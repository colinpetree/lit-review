import { PageShell } from '../../components/ui'
import { navIcon } from '../../lib/navItems'
import DataCard from '../../components/settings/DataCard'

export default function YourDataPage() {
  return (
    <PageShell
      title="Your Data"
      icon={navIcon('/settings/data')}
      description="Your datasets, prompts and results are stored on this computer. Back them up, restore them, or bring back deleted items. API keys are not included in backups."
    >
      <DataCard />
    </PageShell>
  )
}
