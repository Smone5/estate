import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import InvitePage from './routes/Invite'
import OptOutPage from './routes/OptOut'
import DashboardGuard from './components/DashboardGuard'
import IDScanner from './components/IDScanner'
import SemanticSearch from './components/SemanticSearch'
import AdminDashboard from './routes/AdminDashboard'

const PUBLIC_PATHS = ['/invite', '/opt-out']

function DashboardPlaceholder() {
  return (
    <DashboardGuard variant="heir">
      <IDScanner />
      <SemanticSearch />
    </DashboardGuard>
  )
}

function LegalFooter() {
  const location = useLocation()
  const isPublic = PUBLIC_PATHS.some((p) => location.pathname.startsWith(p))
  if (isPublic) return null

  return (
    <footer className="app-footer">
      Disclaimer: The Estate Steward is a collaborative mediation aid designed to assist
      executors and heirs in dividing personal property. It does not provide legal advice,
      estate planning, or tax counsel. Use of this tool does not guarantee probate court
      approval. Executors are advised to consult with a licensed probate attorney regarding
      their fiduciary obligations and court filings.
    </footer>
  )
}

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <header className="app-header">
          <h1>The Estate Steward</h1>
        </header>

        <Routes>
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="/dashboard" element={<DashboardPlaceholder />} />
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/opt-out" element={<OptOutPage />} />
          <Route path="*" element={<Navigate to="/invite/placeholder" replace />} />
        </Routes>

        <LegalFooter />
      </div>
    </BrowserRouter>
  )
}

export default App
