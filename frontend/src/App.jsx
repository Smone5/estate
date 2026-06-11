import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useSearchParams } from 'react-router-dom';
import InvitePage from './routes/Invite';
import OptOutPage from './routes/OptOut';
import DashboardGuard from './components/DashboardGuard';
import IDScanner from './components/IDScanner';
import SemanticSearch from './components/SemanticSearch';
import AdminDashboard from './routes/AdminDashboard';
import FAQDrawer from './components/FAQDrawer';

const PUBLIC_PATHS = ['/invite', '/opt-out'];

function DashboardPlaceholder() {
  return (
    <DashboardGuard variant="heir">
      <IDScanner />
      <SemanticSearch />
    </DashboardGuard>
  );
}

function LegalFooter() {
  const location = useLocation();
  const isPublic = PUBLIC_PATHS.some((p) => location.pathname.startsWith(p));
  if (isPublic) return null;

  return (
    <footer className="app-footer">
      Disclaimer: The Estate Steward is a collaborative mediation aid designed to assist
      executors and heirs in dividing personal property. It does not provide legal advice,
      estate planning, or tax counsel. Use of this tool does not guarantee probate court
      approval. Executors are advised to consult with a licensed probate attorney regarding
      their fiduciary obligations and court filings.
    </footer>
  );
}

function AppShell() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const isHelpOpen = searchParams.get('help') === 'true';
  const isDashboard = location.pathname.startsWith('/dashboard');

  const toggleHelp = () => {
    if (isHelpOpen) {
      setSearchParams({});
    } else {
      setSearchParams({ help: 'true' });
    }
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>The Estate Steward</h1>
        {isDashboard && (
          <button
            onClick={toggleHelp}
            className="close-btn"
            style={{
              color: 'var(--color-text-muted)',
              fontSize: '1.2rem',
              padding: 'var(--space-xs) var(--space-sm)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-sm)',
              background: 'none',
              cursor: 'pointer'
            }}
            aria-label="Toggle Help"
            data-testid="help-trigger-btn"
          >
            ❓
          </button>
        )}
      </header>

      <Routes>
        <Route path="/invite/:token" element={<InvitePage />} />
        <Route path="/dashboard" element={<DashboardPlaceholder />} />
        <Route path="/admin" element={<AdminDashboard />} />
        <Route path="/opt-out" element={<OptOutPage />} />
        <Route path="*" element={<Navigate to="/invite/placeholder" replace />} />
      </Routes>

      <FAQDrawer isOpen={isHelpOpen} onClose={() => setSearchParams({})} />
      <LegalFooter />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}

export default App;
