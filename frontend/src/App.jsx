import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'

function InvitePage() {
  return (
    <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
      <div className="archival-card" style={{ maxWidth: 520, width: '100%' }}>
        <h2 style={{ marginBottom: 'var(--space-lg)' }}>Invitation</h2>
        <p className="text-muted">Loading invitation details...</p>
      </div>
    </div>
  )
}

function DashboardPage() {
  return (
    <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
      <div className="archival-card" style={{ maxWidth: 520, width: '100%' }}>
        <h2 style={{ marginBottom: 'var(--space-lg)' }}>Dashboard</h2>
        <p className="text-muted">Your mediation workspace will appear here.</p>
      </div>
    </div>
  )
}

function AdminPage() {
  return (
    <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
      <div className="archival-card" style={{ maxWidth: 520, width: '100%' }}>
        <h2 style={{ marginBottom: 'var(--space-lg)' }}>Admin Console</h2>
        <p className="text-muted">Admin management panel loading...</p>
      </div>
    </div>
  )
}

function OptOutPage() {
  return (
    <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
      <div className="archival-card text-center" style={{ maxWidth: 480, width: '100%' }}>
        <h2 style={{ marginBottom: 'var(--space-md)' }}>Invitation Declined</h2>
        <p className="text-muted">
          You have declined the consent agreement. No personal data has been saved.
          Your invitation remains uncompleted.
        </p>
      </div>
    </div>
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
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/opt-out" element={<OptOutPage />} />
          <Route path="*" element={<Navigate to="/invite/placeholder" replace />} />
        </Routes>

        <footer className="app-footer">
          Disclaimer: The Estate Steward is a collaborative mediation aid designed to assist
          executors and heirs in dividing personal property. It does not provide legal advice,
          estate planning, or tax counsel. Use of this tool does not guarantee probate court
          approval. Executors are advised to consult with a licensed probate attorney regarding
          their fiduciary obligations and court filings.
        </footer>
      </div>
    </BrowserRouter>
  )
}

export default App