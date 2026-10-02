import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import { useThemeSync } from '../lib/theme'

export default function AppLayout() {
  useThemeSync()
  return (
    <div className="flex h-screen bg-page">
      <Sidebar />
      {/* The page scrolls here, so it keeps the browser's own scrollbar (see index.css). */}
      <main className="page-scroll flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
