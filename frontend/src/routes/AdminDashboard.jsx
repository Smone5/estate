import React, { useState, useEffect } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import DashboardGuard from '../components/DashboardGuard';
import ForceAllocationConsole from '../components/ForceAllocationConsole';
import AdminInventoryDashboard from '../components/AdminInventoryDashboard';
import AdminSessionControl from '../components/AdminSessionControl';
import AdminSetupWizard from '../components/AdminSetupWizard';
import BIP39RestorePanel from '../components/BIP39RestorePanel';
import AdminHelpPortal from '../components/AdminHelpPortal';
import AdminAnnouncementConsole from '../components/AdminAnnouncementConsole';
import AdminSettingsPanel from '../components/AdminSettingsPanel';

export default function AdminDashboard() {
  const store = useMediationStore();
  const sessionStatus = useMediationStore((s) => s.sessionStatus);
  const isDeadlocked = useMediationStore((s) => s.isDeadlocked);
  const sessionId = useMediationStore((s) => s.session_id);
  const userRole = useMediationStore((s) => s.userRole);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState(null);
  const [loggingIn, setLoggingIn] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [showSetupWizard, setShowSetupWizard] = useState(false);
  const [checkingSetupStatus, setCheckingSetupStatus] = useState(true);
  const [viewingSession, setViewingSession] = useState(false);
  const [activeTab, setActiveTab] = useState('inventory');
  const [newSessionTitle, setNewSessionTitle] = useState('');
  const [creatingSession, setCreatingSession] = useState(false);
  const [createSessionError, setCreateSessionError] = useState(null);

  const TABS = [
    { id: 'inventory', label: 'Inventory' },
    { id: 'session', label: 'Session Control' },
    { id: 'backup', label: 'Backup' },
    { id: 'settings', label: 'Settings' },
  ];

  // Determine whether first-boot admin setup has already happened, so we
  // don't show the setup wizard to an already-provisioned instance.
  useEffect(() => {
    if (store.isAuthenticated) {
      setCheckingSetupStatus(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/setup/status');
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setShowSetupWizard(!data.admin_exists);
        }
      } catch (err) {
        console.error('Failed to check setup status', err);
      } finally {
        if (!cancelled) setCheckingSetupStatus(false);
      }
    })();
    return () => { cancelled = true; };
  }, [store.isAuthenticated]);

  // Load sessions if authenticated as admin
  useEffect(() => {
    if (store.isAuthenticated && userRole === 'ADMIN') {
      fetchSessions();
    }
  }, [store.isAuthenticated, userRole]);

  async function fetchSessions() {
    try {
      setLoadingSessions(true);
      const res = await fetch('/api/sessions');
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
      }
    } catch (err) {
      console.error('Failed to load sessions', err);
    } finally {
      setLoadingSessions(false);
    }
  }

  function handleOpenSession(activeSess) {
    store.setSession({
      isAuthenticated: true,
      user_role: 'ADMIN',
      session_id: activeSess.id,
      status: activeSess.status,
      is_deadlocked: activeSess.is_deadlocked,
      is_paused: activeSess.is_paused,
      assets: [],
    });
    setActiveTab('inventory');
    setViewingSession(true);
  }

  async function handleCreateSession(e) {
    e.preventDefault();
    if (!newSessionTitle.trim()) return;
    setCreatingSession(true);
    setCreateSessionError(null);
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ title: newSessionTitle.trim() }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to create session: ${res.status}`);
      }
      const created = await res.json();
      setNewSessionTitle('');
      await fetchSessions();
      handleOpenSession(created);
    } catch (err) {
      setCreateSessionError(err.message);
    } finally {
      setCreatingSession(false);
    }
  }

  function handleBackToSessions() {
    setViewingSession(false);
    fetchSessions();
  }

  async function handleLogin(e) {
    e.preventDefault();
    setLoggingIn(true);
    setAuthError(null);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        throw new Error('Invalid credentials. Please verify and try again.');
      }

      const data = await res.json();
      store.setSession({
        isAuthenticated: true,
        user_role: 'ADMIN',
      });
      // Fetch session details after successful login
      await fetchSessions();
    } catch (err) {
      setAuthError(err.message);
    } finally {
      setLoggingIn(false);
    }
  }

  function handleOverrideComplete() {
    // Refresh session details to clear deadlock status in the UI
    fetchSessions();
  }

  // ── First-Boot Setup Wizard (Gate) ──────────────────────────────────────
  if (!store.isAuthenticated && checkingSetupStatus) {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1, padding: 'var(--space-lg)' }}>
        <p className="text-muted">Checking setup status...</p>
      </div>
    );
  }

  if (!store.isAuthenticated && showSetupWizard) {
    return (
      <AdminSetupWizard
        onSetupComplete={() => setShowSetupWizard(false)}
        onSkipToLogin={() => setShowSetupWizard(false)}
      />
    );
  }

  // ── Login Form (Gate) ──────────────────────────────────────────────────
  if (!store.isAuthenticated || userRole !== 'ADMIN') {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1, padding: 'var(--space-lg)' }}>
        <form onSubmit={handleLogin} className="archival-card" style={{ maxWidth: 440, width: '100%' }}>
          <h2 style={{ marginBottom: 'var(--space-md)' }}>Executor Authentication</h2>
          <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-lg)' }}>
            Please authenticate using your administrator credentials to access the management console.
          </p>

          {authError && (
            <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
              {authError}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            <div>
              <label className="form-label" htmlFor="admin-username">Username</label>
              <input
                id="admin-username"
                className="form-input"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="form-label" htmlFor="admin-password">Password</label>
              <input
                id="admin-password"
                className="form-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <button
              className="btn btn-primary btn-lg"
              type="submit"
              disabled={loggingIn}
              style={{ marginTop: 'var(--space-sm)' }}
            >
              {loggingIn ? 'Authenticating...' : 'Sign In'}
            </button>
          </div>
        </form>
      </div>
    );
  }

  // ── Session Picker (Landing Page) ───────────────────────────────────────
  if (!viewingSession) {
    return (
      <DashboardGuard variant="admin">
        <div className="admin-dashboard-container" style={{ flex: 1, padding: 'var(--space-lg)', overflowY: 'auto' }}>
          <div style={{ maxWidth: 800, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-lg)' }}>
            <div className="flex justify-between items-center">
              <h2 style={{ fontFamily: 'var(--font-serif)' }}>Executor Console</h2>
              <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
                <button className="btn btn-secondary btn-sm" onClick={() => setIsHelpOpen(true)}>
                  Quick-Start & FAQ Guide
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => store.setSession({ isAuthenticated: false, userRole: null })}
                >
                  Log Out
                </button>
              </div>
            </div>

            <div className="archival-card">
              <h3 style={{ marginBottom: 'var(--space-md)' }}>Mediation Sessions</h3>
              {loadingSessions ? (
                <p className="text-muted">Loading sessions...</p>
              ) : sessions.length === 0 ? (
                <p className="text-muted">No sessions yet. Create one below to get started.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                  {sessions.map((s) => (
                    <button
                      key={s.id}
                      className="btn btn-secondary"
                      style={{ justifyContent: 'space-between', display: 'flex', textAlign: 'left' }}
                      onClick={() => handleOpenSession(s)}
                      data-testid={`session-open-${s.id}`}
                    >
                      <span>{s.title}</span>
                      <span className="text-muted text-sm">{s.status}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="archival-card">
              <h3 style={{ marginBottom: 'var(--space-md)' }}>Create New Session</h3>
              {createSessionError && (
                <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
                  {createSessionError}
                </div>
              )}
              <form onSubmit={handleCreateSession} style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                <input
                  className="form-input"
                  type="text"
                  value={newSessionTitle}
                  onChange={(e) => setNewSessionTitle(e.target.value)}
                  placeholder="Session title (e.g. Smith Estate)"
                  style={{ flex: 1, minWidth: '240px' }}
                  data-testid="new-session-title-input"
                />
                <button
                  className="btn btn-primary"
                  type="submit"
                  disabled={creatingSession}
                  data-testid="create-session-btn"
                  style={{ flexGrow: 1 }}
                >
                  {creatingSession ? 'Creating...' : 'Create Session'}
                </button>
              </form>
            </div>
          </div>
        </div>
        <AdminHelpPortal isOpen={isHelpOpen} onClose={() => setIsHelpOpen(false)} sessionId={null} />
      </DashboardGuard>
    );
  }

  // ── Session Console (Tabbed) ─────────────────────────────────────────────
  return (
    <DashboardGuard variant="admin">
      <div className="admin-dashboard-container" style={{ flex: 1, padding: 'var(--space-lg)', overflowY: 'auto' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-lg)' }}>
          <div className="flex justify-between items-center">
            <div>
              <button className="btn btn-link" onClick={handleBackToSessions} data-testid="back-to-sessions-btn">
                ← All Sessions
              </button>
              <h2 style={{ fontFamily: 'var(--font-serif)' }}>Executor Console</h2>
              <p className="text-muted text-sm">
                Status: <strong>{sessionStatus}</strong>
              </p>
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setIsHelpOpen(true)}
              >
                Quick-Start & FAQ Guide
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => store.setSession({ isAuthenticated: false, userRole: null })}
              >
                Log Out
              </button>
            </div>
          </div>

          <div className="admin-tab-nav">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={`btn btn-tab${activeTab === tab.id ? ' active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
                data-testid={`admin-tab-${tab.id}`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {loadingSessions ? (
            <div className="archival-card text-center">
              <p className="text-muted">Syncing session status...</p>
            </div>
          ) : (
            <>
              {activeTab === 'inventory' && (
                <>
                  <AdminInventoryDashboard sessionId={sessionId} />

                  {isDeadlocked ? (
                    <ForceAllocationConsole sessionId={sessionId} onOverrideComplete={handleOverrideComplete} />
                  ) : sessionStatus !== 'SETUP' ? (
                    <div className="archival-card text-center" style={{ padding: 'var(--space-xl)' }}>
                      <h3 style={{ marginBottom: 'var(--space-md)' }}>Mediation Status: Clear</h3>
                      <p className="text-muted" style={{ maxWidth: 480, margin: '0 auto' }}>
                        There are no active deadlocks or allocation conflicts requiring manual force allocation overrides.
                        Heir progress and final keepsake divisions can be monitored via the Session Control panel.
                      </p>
                    </div>
                  ) : null}
                </>
              )}

              {activeTab === 'session' && (
                <>
                  <AdminSessionControl sessionId={sessionId} />
                  {sessionId && <AdminAnnouncementConsole sessionId={sessionId} />}
                </>
              )}

              {activeTab === 'backup' && <BIP39RestorePanel />}

              {activeTab === 'settings' && <AdminSettingsPanel />}
            </>
          )}
        </div>
      </div>
      <AdminHelpPortal
        isOpen={isHelpOpen}
        onClose={() => setIsHelpOpen(false)}
        sessionId={sessionId}
      />
    </DashboardGuard>
  );
}
