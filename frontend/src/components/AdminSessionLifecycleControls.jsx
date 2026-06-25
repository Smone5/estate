import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import { customConfirm } from '../store/useDialogStore';

export default function AdminSessionLifecycleControls({ sessionId, onSessionChanged }) {
  const store = useMediationStore();
  const sessionStatus = useMediationStore((s) => s.sessionStatus);
  const isPaused = useMediationStore((s) => s.isPaused);

  const [actionError, setActionError] = useState(null);
  const [actionSuccess, setActionSuccess] = useState(null);

  const isSetup = sessionStatus === 'SETUP';
  const isActive = sessionStatus === 'ACTIVE' || sessionStatus === 'LOCKED';
  const isFinalized = sessionStatus === 'FINALIZED';

  async function refreshSessionState() {
    if (store.loadSessionDetails) {
      await store.loadSessionDetails();
    }
    if (onSessionChanged) {
      await onSessionChanged();
    }
  }

  async function runSessionAction({
    confirmMessage,
    endpoint,
    errorPrefix,
    successMessage,
  }) {
    if (confirmMessage && !await customConfirm(confirmMessage)) return;

    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/${endpoint}`, {
        method: 'POST',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `${errorPrefix}: ${res.status}`);
      }
      setActionSuccess(successMessage);
      await refreshSessionState();
    } catch (err) {
      setActionError(err.message);
    }
  }

  function handleLaunch() {
    return runSessionAction({
      confirmMessage: 'Launch the session? This will lock the asset catalog and open mediation to all heirs. This action cannot be undone.',
      endpoint: 'launch',
      errorPrefix: 'Launch failed',
      successMessage: 'Session launched. Heirs may now begin mediation.',
    });
  }

  function handlePause() {
    return runSessionAction({
      endpoint: 'pause',
      errorPrefix: 'Pause failed',
      successMessage: 'Session paused. Heir sliders and chat are now frozen.',
    });
  }

  function handleUnpause() {
    return runSessionAction({
      endpoint: 'unpause',
      errorPrefix: 'Unpause failed',
      successMessage: 'Session unpaused. Heir access restored.',
    });
  }

  function handleFinalize() {
    return runSessionAction({
      confirmMessage: 'Finalize the mediation session? This will run the division solver, seal the hash chain, and permanently lock all allocations. This action cannot be undone.',
      endpoint: 'finalize',
      errorPrefix: 'Finalize failed',
      successMessage: 'Session finalized. Keepsake ledgers are available for download.',
    });
  }

  if (!sessionId) {
    return (
      <div className="archival-card">
        <p className="text-muted">No active session selected.</p>
      </div>
    );
  }

  return (
    <div className="admin-session-lifecycle-controls" data-testid="admin-session-lifecycle-controls">
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
    </div>
  );
}
