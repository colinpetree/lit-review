import SettingsPanel from './SettingsPanel'
import LicenseCard from './LicenseCard'
import ThirdPartyCard from './ThirdPartyCard'

export default function LicenseSection() {
  return (
    <SettingsPanel
      title="License and Notices"
      id="license"
      description="The Lit Review license, and where your information is sent when you use it."
    >
      <div className="flex flex-col gap-8">
        <LicenseCard />
        <ThirdPartyCard />
      </div>
    </SettingsPanel>
  )
}
