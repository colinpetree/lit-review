import SettingsPanel from './SettingsPanel'
import AboutCard from './AboutCard'
import UpdatesCard from './UpdatesCard'
import SettingsSection from './SettingsSection'

export default function AboutSection() {
  return (
    <SettingsPanel
      title="About and Updates"
      id="about"
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
    </SettingsPanel>
  )
}
