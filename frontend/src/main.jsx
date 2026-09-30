import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import AppLayout from './components/AppLayout'
import DiscoverPapersPage from './pages/DiscoverPapersPage'
import PaperDataSetsPage from './pages/PaperDataSetsPage'
import DatasetDetailPage from './pages/DatasetDetailPage'
import AnalyzePapersPage from './pages/AnalyzePapersPage'
import PastResultsPage from './pages/PastResultsPage'
import RunResultsPage from './pages/RunResultsPage'
import SettingsPage from './pages/SettingsPage'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/discover" replace />} />
          <Route path="discover" element={<DiscoverPapersPage />} />
          <Route path="datasets" element={<PaperDataSetsPage />} />
          <Route path="datasets/:id" element={<DatasetDetailPage />} />
          <Route path="analyze" element={<AnalyzePapersPage />} />
          <Route path="results" element={<PastResultsPage />} />
          <Route path="results/:id" element={<RunResultsPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
