import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import { useThemeSync } from '../lib/theme'
import useNotConnected from '../lib/useNotConnected'
import { NOT_CONNECTED_MESSAGE } from '../lib/session'

export default function AppLayout() {
  useThemeSync()
  const notConnected = useNotConnected()
  return (
    <div className="flex h-screen bg-page">
      <Sidebar />
      {/* The page scrolls here, so it keeps the browser's own scrollbar (see index.css). */}
      <main className="page-scroll flex-1 overflow-auto">
        {notConnected ? (
          <p
            role="alert"
            className="mx-auto mt-4 max-w-3xl rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200"
          >
            {NOT_CONNECTED_MESSAGE}
          </p>
        ) : null}
        <Outlet />
      </main>
    </div>
  )
}
