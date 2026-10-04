import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import { captureTokenFromLocation } from './lib/session'
import AppLayout from './components/AppLayout'
import DiscoverPapersPage from './pages/DiscoverPapersPage'
import PaperDataSetsPage from './pages/PaperDataSetsPage'
import DatasetDetailPage from './pages/DatasetDetailPage'
import EvaluatePapersPage from './pages/EvaluatePapersPage'
import ScoringPromptsPage from './pages/ScoringPromptsPage'
import PromptDetailPage from './pages/PromptDetailPage'
import PastResultsPage from './pages/PastResultsPage'
import RunResultsPage from './pages/RunResultsPage'
import AiIntegrationsPage from './pages/settings/AiIntegrationsPage'
import ResearchDatabasesPage from './pages/settings/ResearchDatabasesPage'
import YourDataPage from './pages/settings/YourDataPage'
import AppearancePage from './pages/settings/AppearancePage'
import AboutPage from './pages/settings/AboutPage'
import LicensePage from './pages/settings/LicensePage'
import TrashPage from './pages/TrashPage'

// The app opens this page with its secret after the # in the address. Take it, and
// remove it from the address bar, before anything is shown or any call is made.
captureTokenFromLocation()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/discover" replace />} />
          <Route path="discover" element={<DiscoverPapersPage />} />
          <Route path="datasets" element={<PaperDataSetsPage />} />
          <Route path="datasets/:id" element={<DatasetDetailPage />} />
          <Route path="evaluate" element={<EvaluatePapersPage />} />
          <Route path="prompts" element={<ScoringPromptsPage />} />
          <Route path="prompts/:id" element={<PromptDetailPage />} />
          <Route path="results" element={<PastResultsPage />} />
          <Route path="results/:id" element={<RunResultsPage />} />
          <Route path="settings">
            <Route index element={<Navigate to="ai" replace />} />
            <Route path="ai" element={<AiIntegrationsPage />} />
            <Route path="databases" element={<ResearchDatabasesPage />} />
            <Route path="data" element={<YourDataPage />} />
            <Route path="data/trash" element={<TrashPage />} />
            <Route path="appearance" element={<AppearancePage />} />
            <Route path="about" element={<AboutPage />} />
            <Route path="license" element={<LicensePage />} />
            <Route path="*" element={<Navigate to="/settings/ai" replace />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
