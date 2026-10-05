import { PageShell } from '../../components/ui'
import { navIcon } from '../../lib/navItems'
import LicenseCard from '../../components/settings/LicenseCard'
import ThirdPartyCard from '../../components/settings/ThirdPartyCard'

export default function LicensePage() {
  return (
    <PageShell
      title="License and Notices"
      icon={navIcon('/settings/license')}
      description="The Lit Review license, and where your information is sent when you use it."
    >
      <div className="flex flex-col gap-8">
        <LicenseCard />
        <ThirdPartyCard />
      </div>
    </PageShell>
  )
}
