import React, { useState, useEffect } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function AdminAnnouncementConsole({ sessionId }) {
  const store = useMediationStore();
  const currentAnnouncement = useMediationStore((s) => s.announcement);
  const [text, setText] = useState('');
  const [statusMsg, setStatusMsg] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (currentAnnouncement) {
      setText(currentAnnouncement);
    } else {
      setText('');
    }
  }, [currentAnnouncement]);

  async function handleBroadcast(e) {
    e.preventDefault();
    if (!sessionId) return;
    setLoading(true);
    setStatusMsg(null);
    setErrorMsg(null);

    try {
      const res = await fetch(`/api/sessions/${sessionId}/announcement`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ announcement: text }),
      });

      if (!res.ok) {
        throw new Error(`Broadcast failed: ${res.statusText}`);
      }

      const data = await res.json();
      store.setSession({
        ...store,
        session_id: sessionId,
        status: store.sessionStatus,
        announcement: data.announcement,
        announcement_updated_at: data.announcement_updated_at,
      });
      setStatusMsg('Announcement broadcasted successfully.');
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleClear() {
    if (!sessionId) return;
    setLoading(true);
    setStatusMsg(null);
    setErrorMsg(null);

    try {
      const res = await fetch(`/api/sessions/${sessionId}/announcement`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ announcement: null }),
      });

      if (!res.ok) {
        throw new Error(`Clear failed: ${res.statusText}`);
      }

      const data = await res.json();
      store.setSession({
        ...store,
        session_id: sessionId,
        status: store.sessionStatus,
        announcement: null,
        announcement_updated_at: null,
      });
      setText('');
      setStatusMsg('Announcement cleared successfully.');
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="archival-card admin-announcement-card">
      <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-sm)' }}>Active Session Announcement</h3>
      <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-md)' }}>
        Broadcast an estate-specific alert or instruction to all heirs. This message will display immediately on their dashboard and block interaction upon login until acknowledged.
      </p>

      {statusMsg && (
        <div className="banner banner-success" style={{ marginBottom: 'var(--space-md)' }}>
          {statusMsg}
        </div>
      )}
      {errorMsg && (
        <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
          {errorMsg}
        </div>
      )}

      <form onSubmit={handleBroadcast}>
        <div className="announcement-input-wrap">
          <textarea
            id="announcement-input"
            className="form-input"
            rows="4"
            maxLength={500}
            placeholder="Enter announcement text (up to 500 characters)..."
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={loading}
            style={{ width: '100%', resize: 'vertical', minHeight: '100px' }}
          />
          <span 
            className="text-muted text-xs" 
            style={{ position: 'absolute', bottom: 'var(--space-xs)', right: 'var(--space-sm)' }}
          >
            {text.length}/500
          </span>
        </div>

        <div className="announcement-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleClear}
            disabled={loading || !currentAnnouncement}
            style={{ borderColor: 'var(--color-text-muted)' }}
          >
            Clear Announcement
          </button>
          <button
            type="submit"
            className="btn btn-primary btn-sm"
            disabled={loading || !text.trim()}
          >
            {loading ? 'Broadcasting...' : 'Broadcast Announcement'}
          </button>
        </div>
      </form>
    </div>
  );
}
