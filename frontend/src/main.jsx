import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import './index.css'
import { captureTokenFromLocation } from './lib/session'
import AppLayout from './components/AppLayout'
import PaperDataSetsPage from './pages/PaperDataSetsPage'
import DatasetDetailPage from './pages/DatasetDetailPage'
import GradingPromptsPage from './pages/GradingPromptsPage'
import PromptDetailPage from './pages/PromptDetailPage'
import PaperEvaluationsPage from './pages/PaperEvaluationsPage'
import RunResultsPage from './pages/RunResultsPage'
import TrashPage from './pages/TrashPage'
import { TooltipProvider } from './components/ui/Tooltip'

// Old address of one saved evaluation (bookmarks, a remembered last page).
function LegacyRunRedirect() {
  const { id } = useParams()
  return <Navigate to={`/evaluations/${id}`} replace />
}

// Old /evaluate?dataset=<id>: keeps the dataset so New Evaluation opens with it selected.
function LegacyEvaluateRedirect() {
  const dataset = new URLSearchParams(useLocation().search).get('dataset')
  return <Navigate to={`/evaluations?new=1${dataset ? `&dataset=${encodeURIComponent(dataset)}` : ''}`} replace />
}

// The app opens this page with its secret after the # in the address. Take it, and
// remove it from the address bar, before anything is shown or any call is made.
captureTokenFromLocation()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <TooltipProvider>
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/datasets" replace />} />
          <Route path="discover" element={<Navigate to="/datasets?new=1" replace />} />
          <Route path="datasets" element={<PaperDataSetsPage />} />
          <Route path="datasets/:id" element={<DatasetDetailPage />} />
          <Route path="evaluate" element={<LegacyEvaluateRedirect />} />
          <Route path="prompts" element={<GradingPromptsPage />} />
          <Route path="prompts/:id" element={<PromptDetailPage />} />
          <Route path="evaluations" element={<PaperEvaluationsPage />} />
          <Route path="evaluations/:id" element={<RunResultsPage />} />
          <Route path="results" element={<Navigate to="/evaluations" replace />} />
          <Route path="results/:id" element={<LegacyRunRedirect />} />
          <Route path="trash" element={<TrashPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
    </TooltipProvider>
  </StrictMode>,
)
