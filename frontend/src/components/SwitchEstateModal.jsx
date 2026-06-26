import React, { useEffect, useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';

/**
 * Lets a heir who is onboarded into more than one estate session jump
 * between them without logging out and re-entering their password.
 * Only meaningful when the heir's email/username matches heir records in
 * 2+ sessions (see GET /api/auth/heir-sessions).
 */
export default function SwitchEstateModal({ isOpen, onClose }) {
  const loadHeirSessions = useMediationStore((s) => s.loadHeirSessions);
  const switchHeirSession = useMediationStore((s) => s.switchHeirSession);

  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadHeirSessions()
      .then((data) => {
        if (!cancelled) setSessions(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Unable to load your estates.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [isOpen, loadHeirSessions]);

  if (!isOpen) return null;

  async function handleSelect(session) {
    if (session.is_current) {
      onClose();
      return;
    }
    setSwitching(true);
    setError(null);
    try {
      await switchHeirSession(session.session_id);
      onClose();
    } catch (err) {
      setError(err.message || 'Unable to switch estates.');
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.4)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        className="archival-card"
        style={{ maxWidth: 440, width: '90%' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginBottom: 'var(--space-sm)' }}>Switch Estate</h2>
        <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-lg)' }}>
          You are registered as an heir in more than one mediation session.
          Select the estate you would like to view.
        </p>

        {error && (
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        {loading ? (
          <p className="text-muted">Loading your estates...</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            {sessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                className={s.is_current ? 'btn btn-primary' : 'btn btn-secondary'}
                disabled={switching}
                onClick={() => handleSelect(s)}
                style={{ textAlign: 'left' }}
              >
                {s.title}
                {s.is_current && ' (current)'}
              </button>
            ))}
          </div>
        )}

        <button
          type="button"
          className="btn btn-link"
          style={{ marginTop: 'var(--space-md)' }}
          onClick={onClose}
          disabled={switching}
        >
          Close
        </button>
      </div>
    </div>
  );
}
