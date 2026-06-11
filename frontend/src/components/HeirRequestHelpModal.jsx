import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';

const MIN_CHARS = 5;
const MAX_CHARS = 1000;

export default function HeirRequestHelpModal({ onClose }) {
  const sessionId = useMediationStore((s) => s.session_id);
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [sent, setSent] = useState(false);

  const charCount = message.length;
  const isValid = charCount >= MIN_CHARS && charCount <= MAX_CHARS;

  async function handleSend(e) {
    e.preventDefault();
    if (!isValid || !sessionId) return;

    setSending(true);
    setError(null);

    try {
      const res = await fetch(`/api/sessions/${sessionId}/help`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message.trim() }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to send message: ${res.status}`);
      }

      setSent(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  if (sent) {
    return (
      <div
        data-testid="request-help-modal"
        style={{
          position: 'fixed',
          top: 0, left: 0, width: '100vw', height: '100vh',
          background: 'rgba(0,0,0,0.3)',
          display: 'flex', justifyContent: 'center', alignItems: 'center',
          zIndex: 1000,
        }}
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      >
        <div className="archival-card" style={{ maxWidth: 440, width: '90%', textAlign: 'center' }}>
          <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-md)' }}>
            Message Delivered
          </h3>
          <p className="text-muted" style={{ marginBottom: 'var(--space-md)' }}>
            Your message has been delivered to the Executor. They will review it and
            respond as soon as possible.
          </p>
          <button className="btn btn-primary btn-sm" onClick={onClose} data-testid="help-close-btn">
            Close
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      data-testid="request-help-modal"
      style={{
        position: 'fixed',
        top: 0, left: 0, width: '100vw', height: '100vh',
        background: 'rgba(0,0,0,0.3)',
        display: 'flex', justifyContent: 'center', alignItems: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <form
        onSubmit={handleSend}
        className="archival-card"
        style={{ maxWidth: 480, width: '90%' }}
        data-testid="help-form"
      >
        <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-md)' }}>
          Need Assistance? Contact the Executor.
        </h3>

        <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-lg)' }}>
          If you are experiencing issues, have questions about an asset, or feel
          overwhelmed and need a pause, please enter your message below. The
          Executor will be notified immediately.
        </p>

        {error && (
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        <textarea
          className="form-input"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={4}
          placeholder="Describe your question or concern..."
          data-testid="help-message-textarea"
        />

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: 'var(--space-xs)',
            marginBottom: 'var(--space-md)',
          }}
        >
          <p
            className="text-sm"
            data-testid="help-char-counter"
            style={{ color: !isValid && charCount > 0 ? 'var(--color-alert)' : 'var(--color-text-muted)' }}
          >
            {charCount} / {MAX_CHARS} characters
            {charCount > 0 && charCount < MIN_CHARS && ` (minimum ${MIN_CHARS})`}
          </p>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
          <button
            className="btn btn-primary btn-sm"
            type="submit"
            disabled={!isValid || sending}
            data-testid="help-send-btn"
          >
            {sending ? 'Sending...' : 'Send Message'}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            type="button"
            onClick={onClose}
            data-testid="help-cancel-btn"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}