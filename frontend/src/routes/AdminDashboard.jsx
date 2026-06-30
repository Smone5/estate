import React, { useMemo, useState, useEffect } from 'react';
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
import AdminSessionLifecycleControls from '../components/AdminSessionLifecycleControls';
import AdminFinalDocumentsPanel from '../components/AdminFinalDocumentsPanel';

const SESSION_PAGE_SIZE = 8;

function formatSessionDate(value) {
  if (!value) return 'No date';
  try {
    return new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return value;
  }
}

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
  const [restoringAuth, setRestoringAuth] = useState(true);
  const [checkingSetupStatus, setCheckingSetupStatus] = useState(true);
  const [viewingSession, setViewingSession] = useState(Boolean(sessionId));
  const [activeTab, setActiveTab] = useState(
    () => localStorage.getItem('admin_active_tab') || 'inventory'
  );
  function setActiveTabPersisted(tab) {
    localStorage.setItem('admin_active_tab', tab);
    setActiveTab(tab);
  }
  const [sessionSubTab, setSessionSubTab] = useState('register');
  const [newSessionTitle, setNewSessionTitle] = useState('');
  const [creatingSession, setCreatingSession] = useState(false);
  const [createSessionError, setCreateSessionError] = useState(null);
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState('');
  const [sessionSearch, setSessionSearch] = useState('');
  const [sessionStatusFilter, setSessionStatusFilter] = useState('All');
  const [sessionSort, setSessionSort] = useState('created_desc');
  const [sessionView, setSessionView] = useState('comfortable');
  const [sessionPage, setSessionPage] = useState(1);

  const TABS = [
    { id: 'inventory', label: 'Inventory' },
    { id: 'session', label: 'Session' },
    { id: 'backup', label: 'Backup' },
    { id: 'settings', label: 'Settings' },
  ];
  const sessionSubTabs = [
    ...(sessionStatus === 'SETUP' ? [{ id: 'register', label: 'Register Heir' }] : []),
    { id: 'monitor', label: 'Heir Monitor' },
    { id: 'announcement', label: 'Announcement' },
  ];
  const visibleSessionSubTab = sessionSubTabs.some((tab) => tab.id === sessionSubTab)
    ? sessionSubTab
    : sessionSubTabs[0]?.id || 'monitor';
  const selectedSession = sessions.find((s) => s.id === sessionId) || null;
  const sessionStatusCounts = useMemo(() => sessions.reduce((counts, session) => {
    const status = session.status || 'UNKNOWN';
    return { ...counts, [status]: (counts[status] || 0) + 1 };
  }, {}), [sessions]);
  const sessionStatusOptions = useMemo(() => (
    ['All', ...Array.from(new Set(sessions.map((session) => session.status || 'UNKNOWN')))]
  ), [sessions]);
  const filteredSessions = useMemo(() => {
    const query = sessionSearch.trim().toLowerCase();
    const list = sessions.filter((session) => {
      const matchesSearch = !query || [
        session.title,
        session.status,
        session.id,
      ].filter(Boolean).some((value) => String(value).toLowerCase().includes(query));
      const matchesStatus = sessionStatusFilter === 'All' || (session.status || 'UNKNOWN') === sessionStatusFilter;
      return matchesSearch && matchesStatus;
    });

    return [...list].sort((a, b) => {
      if (sessionSort === 'title_asc') return (a.title || '').localeCompare(b.title || '');
      if (sessionSort === 'title_desc') return (b.title || '').localeCompare(a.title || '');
      if (sessionSort === 'status_asc') return (a.status || '').localeCompare(b.status || '');
      if (sessionSort === 'created_asc') return new Date(a.created_at || 0) - new Date(b.created_at || 0);
      return new Date(b.created_at || 0) - new Date(a.created_at || 0);
    });
  }, [sessionSearch, sessionSort, sessionStatusFilter, sessions]);
  const sessionPageCount = Math.max(1, Math.ceil(filteredSessions.length / SESSION_PAGE_SIZE));
  const visibleSessions = filteredSessions.slice(
    (sessionPage - 1) * SESSION_PAGE_SIZE,
    sessionPage * SESSION_PAGE_SIZE,
  );

  // Restore an existing admin cookie before falling back to setup/login gates.
  useEffect(() => {
    if (store.isAuthenticated) {
      setRestoringAuth(false);
      setCheckingSetupStatus(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const authRes = await fetch('/api/auth/me', { credentials: 'same-origin' });
        if (authRes.ok) {
          const authData = await authRes.json();
          if (authData.role === 'ADMIN') {
            store.setSession({
              isAuthenticated: true,
              user_role: 'ADMIN',
              session_id: authData.session_id ?? null,
            });
            if (!cancelled) {
              setViewingSession(Boolean(authData.session_id));
              setShowSetupWizard(false);
              setRestoringAuth(false);
              setCheckingSetupStatus(false);
            }
            await fetchSessions();
            return;
          }
        }
      } catch (err) {
        console.error('Failed to restore admin session', err);
      } finally {
        if (!cancelled) setRestoringAuth(false);
      }

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

  useEffect(() => {
    if (sessionStatus !== 'SETUP' && sessionSubTab === 'register') {
      setSessionSubTab('monitor');
    }
  }, [sessionStatus, sessionSubTab]);

  useEffect(() => {
    if (store.isAuthenticated && userRole === 'ADMIN' && sessionId) {
      setViewingSession(true);
    }
  }, [store.isAuthenticated, userRole, sessionId]);

  useEffect(() => {
    setSessionPage(1);
  }, [sessionSearch, sessionSort, sessionStatusFilter]);

  useEffect(() => {
    if (sessionPage > sessionPageCount) {
      setSessionPage(sessionPageCount);
    }
  }, [sessionPage, sessionPageCount]);

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
    localStorage.setItem('admin_selected_session_id', activeSess.id);
    store.setSession({
      isAuthenticated: true,
      user_role: 'ADMIN',
      session_id: activeSess.id,
      status: activeSess.status,
      is_deadlocked: activeSess.is_deadlocked,
      is_paused: activeSess.is_paused,
      assets: [],
    });
    setActiveTabPersisted('inventory');
    setSessionSubTab(activeSess.status === 'SETUP' ? 'register' : 'monitor');
    setViewingSession(true);
  }

  function startEditingSession(session) {
    setEditingSessionId(session.id);
    setEditingSessionTitle(session.title || '');
  }

  function cancelEditingSession() {
    setEditingSessionId(null);
    setEditingSessionTitle('');
  }

  async function handleRenameSession(targetSession) {
    const title = editingSessionTitle.trim();
    if (!title) return;
    try {
      const res = await fetch(`/api/sessions/${targetSession.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ title }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Rename failed: ${res.status}`);
      }
      setSessions((current) => current.map((session) => (
        session.id === targetSession.id ? { ...session, title } : session
      )));
      cancelEditingSession();
    } catch (err) {
      setCreateSessionError(err.message);
    }
  }

  async function handleDeleteSession(targetSession) {
    if (!window.confirm(`Delete session "${targetSession.title}"? This cannot be undone.`)) return;
    try {
      const res = await fetch(`/api/sessions/${targetSession.id}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Delete failed: ${res.status}`);
      }
      if (sessionId === targetSession.id) {
        localStorage.removeItem('admin_selected_session_id');
        setViewingSession(false);
        store.setSession({
          isAuthenticated: true,
          user_role: 'ADMIN',
          session_id: null,
        });
      }
      await fetchSessions();
    } catch (err) {
      setCreateSessionError(err.message);
    }
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

  async function handleLogout() {
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
      });
    } catch (err) {
      console.error('Failed to clear auth cookie', err);
    } finally {
      localStorage.removeItem('admin_selected_session_id');
      setViewingSession(false);
      setSessions([]);
      store.setSession({
        isAuthenticated: false,
        user_role: null,
        session_id: null,
      });
    }
  }

  // ── First-Boot Setup Wizard (Gate) ──────────────────────────────────────
  if (!store.isAuthenticated && restoringAuth) {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1, padding: 'var(--space-lg)' }}>
        <p className="text-muted">Restoring Executor Session</p>
      </div>
    );
  }

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
            <div className="admin-console-header">
              <h2 style={{ fontFamily: 'var(--font-serif)' }}>Executor Console</h2>
              <div className="admin-console-actions">
                <button className="btn btn-secondary btn-sm" onClick={() => setIsHelpOpen(true)}>
                  Quick-Start & FAQ Guide
                </button>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleLogout}
                >
                  Log Out
                </button>
              </div>
            </div>

            <div className="archival-card admin-session-index">
              <div className="admin-session-index-header">
                <div>
                  <h3>Mediation Sessions</h3>
                  <p className="text-sm text-muted">
                    Find an estate, review its status, and jump back into the active workflow.
                  </p>
                </div>
                <div className="admin-session-summary">
                  <span>{sessions.length} total</span>
                  {Object.entries(sessionStatusCounts).slice(0, 3).map(([status, count]) => (
                    <span key={status}>{count} {status.toLowerCase()}</span>
                  ))}
                </div>
              </div>
              {loadingSessions ? (
                <p className="text-muted">Loading sessions...</p>
              ) : sessions.length === 0 ? (
                <p className="text-muted">No sessions yet. Create one below to get started.</p>
              ) : (
                <>
                  <div className="admin-session-toolbar" aria-label="Session controls">
                    <div className="admin-session-search">
                      <label className="form-label text-xs" htmlFor="admin-session-search">Search sessions</label>
                      <input
                        id="admin-session-search"
                        className="form-input"
                        type="search"
                        value={sessionSearch}
                        onChange={(e) => setSessionSearch(e.target.value)}
                        placeholder="Estate name, status, or ID"
                        data-testid="session-search-input"
                      />
                    </div>
                    <div>
                      <label className="form-label text-xs" htmlFor="admin-session-status-filter">Status</label>
                      <select
                        id="admin-session-status-filter"
                        className="form-input"
                        value={sessionStatusFilter}
                        onChange={(e) => setSessionStatusFilter(e.target.value)}
                        data-testid="session-status-filter"
                      >
                        {sessionStatusOptions.map((status) => (
                          <option key={status} value={status}>
                            {status === 'All' ? 'All statuses' : status}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="form-label text-xs" htmlFor="admin-session-sort">Sort</label>
                      <select
                        id="admin-session-sort"
                        className="form-input"
                        value={sessionSort}
                        onChange={(e) => setSessionSort(e.target.value)}
                        data-testid="session-sort-select"
                      >
                        <option value="created_desc">Newest first</option>
                        <option value="created_asc">Oldest first</option>
                        <option value="title_asc">Title A-Z</option>
                        <option value="title_desc">Title Z-A</option>
                        <option value="status_asc">Status</option>
                      </select>
                    </div>
                    <div>
                      <label className="form-label text-xs">View</label>
                      <div className="admin-session-view-toggle">
                        <button
                          type="button"
                          className={sessionView === 'comfortable' ? 'active' : ''}
                          onClick={() => setSessionView('comfortable')}
                          data-testid="session-view-comfortable"
                        >
                          Cards
                        </button>
                        <button
                          type="button"
                          className={sessionView === 'compact' ? 'active' : ''}
                          onClick={() => setSessionView('compact')}
                          data-testid="session-view-compact"
                        >
                          List
                        </button>
                      </div>
                    </div>
                  </div>

                  {filteredSessions.length === 0 ? (
                    <div className="admin-session-empty">
                      <strong>No matching sessions</strong>
                      <span>Try a broader search or clear the status filter.</span>
                    </div>
                  ) : (
                    <div className={`admin-session-collection admin-session-collection--${sessionView}`}>
                  {visibleSessions.map((s) => (
                    <div key={s.id} className={`admin-session-row admin-session-row--${sessionView}`}>
                      {editingSessionId === s.id ? (
                        <>
                          <input
                            className="form-input"
                            value={editingSessionTitle}
                            onChange={(e) => setEditingSessionTitle(e.target.value)}
                            data-testid={`edit-session-title-input-${s.id}`}
                            aria-label="Session title"
                          />
                          <button
                            className="btn btn-primary btn-sm"
                            type="button"
                            onClick={() => handleRenameSession(s)}
                            data-testid={`save-session-btn-${s.id}`}
                          >
                            Save
                          </button>
                          <button
                            className="btn btn-secondary btn-sm"
                            type="button"
                            onClick={cancelEditingSession}
                            data-testid={`cancel-session-btn-${s.id}`}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="admin-session-open-btn"
                            onClick={() => handleOpenSession(s)}
                            data-testid={`session-open-${s.id}`}
                          >
                            <span className="admin-session-title">{s.title}</span>
                            <span className={`admin-session-status admin-session-status--${(s.status || 'unknown').toLowerCase()}`}>
                              {s.status || 'UNKNOWN'}
                            </span>
                            <span className="admin-session-date">{formatSessionDate(s.created_at)}</span>
                          </button>
                          <div className="admin-session-row-actions">
                            <button
                              className="btn btn-primary btn-sm"
                              type="button"
                              onClick={() => handleOpenSession(s)}
                              data-testid={`open-session-btn-${s.id}`}
                            >
                              Open
                            </button>
                            <button
                              className="btn btn-secondary btn-sm"
                              type="button"
                              onClick={() => startEditingSession(s)}
                              data-testid={`edit-session-btn-${s.id}`}
                            >
                              Rename
                            </button>
                            <button
                              className="btn btn-danger btn-sm"
                              type="button"
                              onClick={() => handleDeleteSession(s)}
                              data-testid={`delete-session-${s.id}`}
                            >
                              Delete
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                    </div>
                  )}

                  {filteredSessions.length > SESSION_PAGE_SIZE && (
                    <div className="admin-session-pagination" aria-label="Session pagination">
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setSessionPage((page) => Math.max(1, page - 1))}
                        disabled={sessionPage === 1}
                      >
                        Previous
                      </button>
                      <span>
                        Page {sessionPage} of {sessionPageCount}
                      </span>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setSessionPage((page) => Math.min(sessionPageCount, page + 1))}
                        disabled={sessionPage === sessionPageCount}
                      >
                        Next
                      </button>
                    </div>
                  )}
                </>
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
          <div className="admin-console-header">
            <div>
              <button className="btn btn-secondary btn-sm admin-back-btn" onClick={handleBackToSessions} data-testid="back-to-sessions-btn">
                ← All Sessions
              </button>
              <h2 style={{ fontFamily: 'var(--font-serif)' }}>Executor Console</h2>
              <p className="text-muted text-sm">
                Status: <strong>{sessionStatus}</strong>
              </p>
            </div>
            <div className="admin-console-actions">
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => setIsHelpOpen(true)}
              >
                Quick-Start & FAQ Guide
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleLogout}
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
                onClick={() => setActiveTabPersisted(tab.id)}
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
                  {sessionStatus === 'ACTIVE' || sessionStatus === 'LOCKED' ? (
                    <AdminSessionLifecycleControls sessionId={sessionId} onSessionChanged={fetchSessions} />
                  ) : null}

                  {sessionStatus === 'FINALIZED' ? (
                    <AdminFinalDocumentsPanel
                      sessionId={sessionId}
                      sessionTitle={selectedSession?.title}
                      heirs={[]}
                    />
                  ) : null}

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
                <div className="admin-session-workspace">
                  <div className="admin-subtab-nav" aria-label="Session control sections">
                    {sessionSubTabs.map((tab) => (
                      <button
                        key={tab.id}
                        type="button"
                        className={`btn btn-tab${visibleSessionSubTab === tab.id ? ' active' : ''}`}
                        onClick={() => setSessionSubTab(tab.id)}
                        data-testid={`admin-session-subtab-${tab.id}`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </div>

                  {visibleSessionSubTab === 'register' && (
                    <AdminSessionControl sessionId={sessionId} section="register" />
                  )}
                  {visibleSessionSubTab === 'monitor' && (
                    <AdminSessionControl sessionId={sessionId} section="monitor" />
                  )}
                  {visibleSessionSubTab === 'announcement' && sessionId && (
                    <AdminAnnouncementConsole sessionId={sessionId} />
                  )}
                </div>
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
