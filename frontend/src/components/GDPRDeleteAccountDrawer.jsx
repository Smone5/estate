import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function GDPRDeleteAccountDrawer() {
  const store = useMediationStore();
  const username = useMediationStore((s) => s.legal_first_name) || '';
  const [isOpen, setIsOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);

  const matches = confirmText === username && username.length > 0;

  async function handleDelete() {
    if (!matches || deleting) return;

    setDeleting(true);
    setError(null);

    try {
      await store.deleteAccount();
      setIsOpen(false);
      setConfirmText('');
    } catch (err) {
      setError(err.message || 'Account deletion failed.');
    } finally {
      setDeleting(false);
    }
  }

  function handleClose() {
    setIsOpen(false);
    setError(null);
    setConfirmText('');
  }

  return (
    <>
      <button
        className="btn btn-secondary btn-sm"
        onClick={() => setIsOpen(true)}
        style={{ width: '100%', color: '#DC2626', borderColor: '#DC2626' }}
        data-testid="delete-account-trigger-btn"
      >
        Delete My Account & Data
      </button>

      {isOpen && (
        <div
          data-testid="delete-account-drawer"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            width: '100vw',
            height: '100vh',
            background: 'rgba(0,0,0,0.3)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 1000,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) handleClose();
          }}
        >
          <div
            className="archival-card"
            style={{
              maxWidth: 480,
              width: '90%',
              maxHeight: '90vh',
              overflowY: 'auto',
            }}
          >
            <h3
              style={{
                fontFamily: 'var(--font-serif)',
                marginBottom: 'var(--space-md)',
                color: '#DC2626',
              }}
            >
              Delete Account & Data
            </h3>

            <div
              style={{
                background: 'var(--color-alert-light)',
                border: '1px solid var(--color-alert)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-md)',
                marginBottom: 'var(--space-lg)',
                fontSize: '0.85rem',
              }}
            >
              <strong>⚠️ Warning:</strong> This will permanently anonymize your
              account. Your chat transcripts will be deleted, your profile will
              be scrubbed of all PII, and your LangGraph checkpointer state will
              be purged. Your points allocations and shared memories will be
              retained for probate ledger integrity.
              <br />
              <br />
              This action is required under GDPR Article 17 (Right to Erasure).
              Once completed, it cannot be undone.
            </div>

            <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-md)' }}>
              To confirm, type your username exactly as shown:
            </p>

            <div
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-sm) var(--space-md)',
                marginBottom: 'var(--space-sm)',
                fontFamily: 'monospace',
                fontSize: '0.9rem',
              }}
            >
              {username}
            </div>

            <input
              className="form-input"
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={`Type "${username}" to confirm`}
              style={{ marginBottom: 'var(--space-md)' }}
              data-testid="delete-confirm-input"
            />

            {error && (
              <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
                {error}
              </div>
            )}

            <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleDelete}
                disabled={!matches || deleting}
                style={{
                  background: '#DC2626',
                  borderColor: '#DC2626',
                  opacity: matches && !deleting ? 1 : 0.5,
                }}
                data-testid="delete-confirm-btn"
              >
                {deleting ? 'Anonymizing...' : 'Yes, Delete My Account'}
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={handleClose}
                data-testid="delete-cancel-btn"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}