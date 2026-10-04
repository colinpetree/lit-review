import { PageShell } from '../../components/ui'
import { navIcon } from '../../lib/navItems'
import LicenseCard from '../../components/settings/LicenseCard'

export default function LicensePage() {
  return (
    <PageShell
      title="License and Notices"
      icon={navIcon('/settings/license')}
      description={
        <>
          The{' '}
          <a
            href="https://github.com/colinpetree/lit-review"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 underline-offset-2 hover:text-blue-800 hover:underline dark:text-blue-400 dark:hover:text-blue-300"
          >
            Lit Review
          </a>{' '}
          license, and where your information is sent when you use it.
        </>
      }
    >
      <LicenseCard />
    </PageShell>
  )
}
