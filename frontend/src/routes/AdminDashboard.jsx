import React, { useState, useEffect } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import DashboardGuard from '../components/DashboardGuard';
import ForceAllocationConsole from '../components/ForceAllocationConsole';
import AdminInventoryDashboard from '../components/AdminInventoryDashboard';
import AdminHelpPortal from '../components/AdminHelpPortal';
import AdminAnnouncementConsole from '../components/AdminAnnouncementConsole';

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
        if (data.length > 0 && !sessionId) {
          // Auto-select first session
          const activeSess = data[0];
          store.setSession({
            isAuthenticated: true,
            user_role: 'ADMIN',
            session_id: activeSess.id,
            status: activeSess.status,
            is_deadlocked: activeSess.is_deadlocked,
            is_paused: activeSess.is_paused,
            assets: [],
          });
        }
      }
    } catch (err) {
      console.error('Failed to load sessions', err);
    } finally {
      setLoadingSessions(false);
    }
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

  return (
    <DashboardGuard variant="admin">
      <div className="admin-dashboard-container" style={{ flex: 1, padding: 'var(--space-lg)', overflowY: 'auto' }}>
        <div style={{ maxWidth: 1000, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-lg)' }}>
          <div className="flex justify-between items-center">
            <div>
              <h2 style={{ fontFamily: 'var(--font-serif)' }}>Executor Console</h2>
              {sessions.length > 0 && (
                <p className="text-muted text-sm">
                  Active Session: <strong>{sessions[0].title}</strong> | Status: <strong>{sessionStatus}</strong>
                </p>
              )}
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

          {loadingSessions ? (
            <div className="archival-card text-center">
              <p className="text-muted">Syncing session status...</p>
            </div>
          ) : (
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

              {sessionId && <AdminAnnouncementConsole sessionId={sessionId} />}
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
