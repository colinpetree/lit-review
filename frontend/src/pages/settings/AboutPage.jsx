import { PageShell } from '../../components/ui'
import { navIcon } from '../../lib/navItems'
import AboutCard from '../../components/settings/AboutCard'
import UpdatesCard from '../../components/settings/UpdatesCard'
import SettingsSection from '../../components/settings/SettingsSection'

export default function AboutPage() {
  return (
    <PageShell
      title="About and Updates"
      icon={navIcon('/settings/about')}
      description="Your version, where your data and log are stored, and whether Lit Review checks for updates."
    >
      <div className="flex flex-col gap-8">
        <SettingsSection title="This copy">
          <AboutCard />
        </SettingsSection>
        <SettingsSection title="Updates">
          <UpdatesCard />
        </SettingsSection>
      </div>
    </PageShell>
  )
}
