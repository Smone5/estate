import React, { useState, useEffect, useCallback } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function AdminSessionControl({ sessionId }) {
  const store = useMediationStore();
  const sessionStatus = useMediationStore((s) => s.sessionStatus);
  const isPaused = useMediationStore((s) => s.isPaused);

  const [heirs, setHeirs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState(null);
  const [actionSuccess, setActionSuccess] = useState(null);

  // Registration form
  const [regForm, setRegForm] = useState({
    username: '',
    email: '',
    phone: '',
    physical_address: '',
  });
  const [registering, setRegistering] = useState(false);

  // ── Fetch heirs ─────────────────────────────────────────────────────────
  const fetchHeirs = useCallback(async () => {
    if (!sessionId) return;
    try {
      setLoading(true);
      const res = await fetch(`/api/sessions/${sessionId}/heirs`);
      if (res.ok) {
        const data = await res.json();
        setHeirs(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to fetch heirs', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchHeirs();
  }, [fetchHeirs]);

  // Clear action messages after timeout
  useEffect(() => {
    if (actionError || actionSuccess) {
      const timer = setTimeout(() => {
        setActionError(null);
        setActionSuccess(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [actionError, actionSuccess]);

  // ── Register Heir ───────────────────────────────────────────────────────
  async function handleRegisterHeir(e) {
    e.preventDefault();
    if (!regForm.username.trim() || !regForm.email.trim()) {
      setActionError('Display Name and Email are required.');
      return;
    }

    setRegistering(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      const res = await fetch(`/api/sessions/${sessionId}/heirs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: regForm.username.trim(),
          email: regForm.email.trim(),
          phone: regForm.phone.trim() || null,
          physical_address: regForm.physical_address.trim() || null,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Registration failed: ${res.status}`);
      }

      setRegForm({ username: '', email: '', phone: '', physical_address: '' });
      setActionSuccess('Heir registered successfully.');
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setRegistering(false);
    }
  }

  // ── Send Invite ─────────────────────────────────────────────────────────
  async function handleSendInvite(heirId) {
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/heirs/${heirId}/send-invite`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Send invite failed: ${res.status}`);
      }
      setActionSuccess('Invitation email dispatched.');
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    }
  }

  // ── Regenerate Token ────────────────────────────────────────────────────
  async function handleRegenerateToken(heirId) {
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/heirs/${heirId}/invite-token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Token regeneration failed: ${res.status}`);
      }
      setActionSuccess('Invite token regenerated.');
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    }
  }

  // ── Copy Token to Clipboard ─────────────────────────────────────────────
  function handleCopyToken(token) {
    navigator.clipboard.writeText(token).then(
      () => setActionSuccess('Token copied to clipboard.'),
      () => setActionError('Failed to copy token.'),
    );
  }

  // ── Delete Heir ─────────────────────────────────────────────────────────
  async function handleDeleteHeir(heirId, heirName) {
    if (!window.confirm(`Permanently delete heir "${heirName}"? This will purge all PII, chat history, and ID scans. This action cannot be undone.`)) {
      return;
    }

    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/heirs/${heirId}`, { method: 'DELETE' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Delete heir failed: ${res.status}`);
      }
      setActionSuccess('Heir deleted and PII purged.');
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    }
  }

  // ── Session Controls ────────────────────────────────────────────────────
  async function handleLaunch() {
    if (!window.confirm('Launch the session? This will lock the asset catalog and open mediation to all heirs. This action cannot be undone.')) return;

    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/launch`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Launch failed: ${res.status}`);
      }
      setActionSuccess('Session launched. Heirs may now begin mediation.');
      store.loadSessionDetails();
    } catch (err) {
      setActionError(err.message);
    }
  }

  async function handlePause() {
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/pause`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Pause failed: ${res.status}`);
      }
      setActionSuccess('Session paused. Heir sliders and chat are now frozen.');
      store.loadSessionDetails();
    } catch (err) {
      setActionError(err.message);
    }
  }

  async function handleUnpause() {
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/unpause`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Unpause failed: ${res.status}`);
      }
      setActionSuccess('Session unpaused. Heir access restored.');
      store.loadSessionDetails();
    } catch (err) {
      setActionError(err.message);
    }
  }

  async function handleFinalize() {
    if (!window.confirm('Finalize the mediation session? This will run the division solver, seal the hash chain, and permanently lock all allocations. This action cannot be undone.')) return;

    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/finalize`, { method: 'POST' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Finalize failed: ${res.status}`);
      }
      setActionSuccess('Session finalized. Keepsake ledgers are available for download.');
      store.loadSessionDetails();
    } catch (err) {
      setActionError(err.message);
    }
  }

  // ── Status helpers ──────────────────────────────────────────────────────
  function statusCheckmark(status) {
    if (status === 'SUBMITTED') return '✅';
    if (status === 'ABSTAINED') return '⚪ Abstained';
    if (status === 'EXPIRED_NON_PARTICIPATING') return '⏹ Expired';
    if (status === 'PROFILE_HOLD') return '🆔 ID Hold';
    if (status === 'ACTIVE') return '⏳ Active';
    return '⏳ Pending';
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────
  const isSetup = sessionStatus === 'SETUP';
  const isActive = sessionStatus === 'ACTIVE' || sessionStatus === 'LOCKED';
  const isFinalized = sessionStatus === 'FINALIZED';

  if (!sessionId) {
    return (
      <div className="archival-card">
        <p className="text-muted">No active session selected.</p>
      </div>
    );
  }

  return (
    <div className="admin-session-control" data-testid="admin-session-control">
      {/* Action feedback */}
      {actionError && (
        <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
          {actionError}
        </div>
      )}
      {actionSuccess && (
        <div className="banner banner-success" style={{ marginBottom: 'var(--space-md)' }}>
          {actionSuccess}
        </div>
      )}

      {/* Session Status Banner */}
      <div
        className="archival-card"
        style={{
          marginBottom: 'var(--space-lg)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 'var(--space-sm)',
        }}
      >
        <div>
          <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: '4px' }}>
            Session Status: <strong>{sessionStatus}</strong>
            {isPaused && sessionStatus !== 'SETUP' && ' (Paused)'}
          </h3>
          <p className="text-muted text-sm">
            {isSetup && 'Setup Phase. Stage and publish assets, then launch the session.'}
            {isActive && !isPaused && 'Mediation active. Heirs are allocating points.'}
            {isActive && isPaused && 'Session paused. Heir access is frozen.'}
            {isFinalized && 'Mediation finalized. Distribution ledgers are sealed.'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
          {isSetup && (
            <button
              className="btn btn-primary btn-sm"
              onClick={handleLaunch}
              data-testid="launch-session-btn"
            >
              🚀 Launch Session
            </button>
          )}
          {isActive && !isPaused && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={handlePause}
              data-testid="pause-session-btn"
            >
              ⏸ Pause Session
            </button>
          )}
          {isActive && isPaused && (
            <button
              className="btn btn-primary btn-sm"
              onClick={handleUnpause}
              data-testid="unpause-session-btn"
            >
              ▶ Unpause Session
            </button>
          )}
          {isActive && (
            <button
              className="btn btn-primary btn-sm"
              onClick={handleFinalize}
              style={{ background: 'var(--color-alert)', borderColor: 'var(--color-alert)' }}
              data-testid="finalize-session-btn"
            >
              🔒 Finalize & Seal
            </button>
          )}
        </div>
      </div>

      {/* Heir Registration Panel (Setup only) */}
      {isSetup && (
        <div className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
          <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-md)' }}>
            Register Heir
          </h3>
          <form onSubmit={handleRegisterHeir}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-sm) var(--space-md)' }}>
              <div>
                <label className="form-label" htmlFor="heir-username">
                  Display Name *
                </label>
                <input
                  id="heir-username"
                  className="form-input"
                  value={regForm.username}
                  onChange={(e) => setRegForm((p) => ({ ...p, username: e.target.value }))}
                  placeholder="e.g. Alice Smith"
                  data-testid="heir-reg-username"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-email">
                  Email Address *
                </label>
                <input
                  id="heir-email"
                  className="form-input"
                  type="email"
                  value={regForm.email}
                  onChange={(e) => setRegForm((p) => ({ ...p, email: e.target.value }))}
                  placeholder="alice@example.com"
                  data-testid="heir-reg-email"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-phone">
                  Phone (optional)
                </label>
                <input
                  id="heir-phone"
                  className="form-input"
                  type="tel"
                  value={regForm.phone}
                  onChange={(e) => setRegForm((p) => ({ ...p, phone: e.target.value }))}
                  placeholder="+1 (555) 123-4567"
                  data-testid="heir-reg-phone"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-address">
                  Physical Address (optional)
                </label>
                <input
                  id="heir-address"
                  className="form-input"
                  value={regForm.physical_address}
                  onChange={(e) => setRegForm((p) => ({ ...p, physical_address: e.target.value }))}
                  placeholder="123 Main St, Anytown, USA"
                  data-testid="heir-reg-address"
                />
              </div>
            </div>
            <button
              className="btn btn-primary btn-sm"
              type="submit"
              disabled={registering}
              style={{ marginTop: 'var(--space-md)' }}
              data-testid="heir-reg-submit"
            >
              {registering ? 'Registering...' : 'Register Heir'}
            </button>
          </form>
        </div>
      )}

      {/* Heir Monitor Table */}
      <div className="archival-card">
        <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-md)' }}>
          Heir Monitor
        </h3>

        {loading ? (
          <p className="text-muted">Loading heirs...</p>
        ) : heirs.length === 0 ? (
          <p className="text-muted">
            {isSetup
              ? 'No heirs registered yet. Use the form above to add beneficiaries.'
              : 'No heirs registered for this session.'}
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table
              className="heir-monitor-table"
              data-testid="heir-monitor-table"
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: '0.85rem',
              }}
            >
              <thead>
                <tr style={{ borderBottom: '2px solid var(--color-border)' }}>
                  <th style={thStyle}>Name</th>
                  <th style={thStyle}>Email</th>
                  <th style={thStyle}>Phone</th>
                  <th style={thStyle}>Address</th>
                  <th style={thStyle}>Status</th>
                  <th style={thStyle}>Invite Token</th>
                  <th style={thStyle}>Dispatched</th>
                  <th style={thStyle}>Expires</th>
                  <th style={thStyle}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {heirs.map((heir) => (
                  <tr
                    key={heir.id}
                    data-testid={`heir-row-${heir.id}`}
                    style={{ borderBottom: '1px solid var(--color-border)' }}
                  >
                    <td style={tdStyle}>
                      {heir.username || `${heir.legal_first_name || ''} ${heir.legal_last_name || ''}`.trim() || '—'}
                    </td>
                    <td style={tdStyle}>{heir.email || '—'}</td>
                    <td style={tdStyle}>{heir.phone || '—'}</td>
                    <td style={{ ...tdStyle, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {heir.physical_address || '—'}
                    </td>
                    <td style={tdStyle}>{statusCheckmark(heir.user_status || heir.status)}</td>
                    <td style={tdStyle}>
                      {heir.invite_token ? (
                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <code style={{ fontSize: '0.7rem' }}>
                            {heir.invite_token.substring(0, 8)}...
                          </code>
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '0 4px', fontSize: '0.65rem', lineHeight: 1.2 }}
                            onClick={() => handleCopyToken(heir.invite_token)}
                            title="Copy token"
                            data-testid={`copy-token-${heir.id}`}
                          >
                            📋
                          </button>
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td style={tdStyle}>{formatDate(heir.invite_dispatched_at)}</td>
                    <td style={tdStyle}>{formatDate(heir.invite_token_expires_at)}</td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        {isSetup && (
                          <>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => handleRegenerateToken(heir.id)}
                              style={{ fontSize: '0.65rem', padding: '2px 6px' }}
                              data-testid={`regen-token-${heir.id}`}
                            >
                              🔄 Token
                            </button>
                            <button
                              className="btn btn-primary btn-sm"
                              onClick={() => handleSendInvite(heir.id)}
                              style={{ fontSize: '0.65rem', padding: '2px 6px' }}
                              data-testid={`send-invite-${heir.id}`}
                            >
                              ✉ Send
                            </button>
                          </>
                        )}
                        {isSetup && (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleDeleteHeir(heir.id, heir.username || heir.email)}
                            style={{ fontSize: '0.65rem', padding: '2px 6px', color: '#DC2626' }}
                            data-testid={`delete-heir-${heir.id}`}
                          >
                            🗑
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const thStyle = {
  padding: 'var(--space-sm)',
  textAlign: 'left',
  fontWeight: 600,
  color: 'var(--color-text)',
  whiteSpace: 'nowrap',
};

const tdStyle = {
  padding: 'var(--space-sm)',
  verticalAlign: 'top',
  color: 'var(--color-text)',
};