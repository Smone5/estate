import React, { useState } from 'react';

export default function AdminInspectIDModal({ heir, onClose, onVerificationComplete }) {
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectionReason, setRejectionReason] = useState('');
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [error, setError] = useState(null);

  if (!heir) return null;

  async function handleApprove() {
    setApproving(true);
    setError(null);
    try {
      const res = await fetch(`/api/heirs/${heir.id}/verify-identity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'approve' }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Verification failed: ${res.status}`);
      }
      if (onVerificationComplete) onVerificationComplete();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setApproving(false);
    }
  }

  async function handleReject() {
    if (!rejectionReason.trim()) {
      setError('Please provide a reason for rejection.');
      return;
    }

    setRejecting(true);
    setError(null);
    try {
      const res = await fetch(`/api/heirs/${heir.id}/verify-identity`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'reject', reason: rejectionReason.trim() }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Rejection failed: ${res.status}`);
      }
      if (onVerificationComplete) onVerificationComplete();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setRejecting(false);
    }
  }

  return (
    <div
      data-testid="admin-inspect-id-modal"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        background: 'rgba(0,0,0,0.4)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="archival-card"
        style={{
          maxWidth: 900,
          width: '95%',
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: '1.4rem',
            marginBottom: 'var(--space-lg)',
          }}
        >
          Inspect Beneficiary Identity
        </h2>

        {error && (
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: 'var(--space-lg)',
          }}
        >
          {/* Left Pane — ID Scan */}
          <div>
            <h4 style={{ marginBottom: 'var(--space-sm)' }}>Government ID Scan</h4>
            <div
              data-testid="id-scan-pane"
              style={{
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--color-bg)',
                minHeight: 300,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                overflow: 'hidden',
              }}
            >
              {heir.id_scan_uri ? (
                <img
                  src={heir.id_scan_uri}
                  alt="Government ID scan"
                  data-testid="id-scan-image"
                  style={{
                    maxWidth: '100%',
                    maxHeight: 400,
                    objectFit: 'contain',
                  }}
                />
              ) : (
                <p className="text-muted">No ID scan uploaded</p>
              )}
            </div>
          </div>

          {/* Right Pane — Legal Details */}
          <div>
            <h4 style={{ marginBottom: 'var(--space-sm)' }}>Heir Legal Details</h4>
            <div
              data-testid="legal-details-pane"
              style={{
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-md)',
                background: 'var(--color-bg)',
              }}
            >
              <DetailRow label="Legal Name" value={
                [heir.legal_first_name, heir.legal_middle_name, heir.legal_last_name]
                  .filter(Boolean).join(' ') || '—'
              } />
              <DetailRow label="Date of Birth" value={heir.date_of_birth || '—'} />
              <DetailRow label="Relationship" value={heir.relationship_to_decedent || '—'} />
              <DetailRow label="Username" value={heir.username || '—'} />
              <DetailRow label="Email" value={heir.email || '—'} />
              <DetailRow label="Phone" value={heir.phone || '—'} />
              <DetailRow label="Physical Address" value={heir.physical_address || '—'} />
              <DetailRow label="ID Verified" value={heir.identity_verified ? '✓ Yes' : '✗ No'} />
            </div>
          </div>
        </div>

        {/* Rejection reason */}
        {showRejectForm && (
          <div style={{ marginTop: 'var(--space-md)' }}>
            <label className="form-label" htmlFor="rejection-reason">
              Rejection Reason (required)
            </label>
            <textarea
              id="rejection-reason"
              className="form-input"
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              rows={3}
              placeholder="e.g. Name spelling on ID does not match profile..."
              data-testid="rejection-reason-textarea"
            />
          </div>
        )}

        {/* Action Buttons */}
        <div
          style={{
            display: 'flex',
            gap: 'var(--space-sm)',
            marginTop: 'var(--space-lg)',
            justifyContent: 'flex-end',
          }}
        >
          <button
            className="btn btn-secondary btn-sm"
            onClick={onClose}
            data-testid="inspect-id-cancel-btn"
          >
            Cancel
          </button>

          {!showRejectForm ? (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setShowRejectForm(true)}
              style={{
                color: 'var(--color-alert)',
                borderColor: 'var(--color-alert)',
              }}
              data-testid="reject-trigger-btn"
            >
              Reject & Flag
            </button>
          ) : (
            <button
              className="btn btn-primary btn-sm"
              onClick={handleReject}
              disabled={rejecting || !rejectionReason.trim()}
              style={{
                background: 'var(--color-alert)',
                borderColor: 'var(--color-alert)',
              }}
              data-testid="reject-confirm-btn"
            >
              {rejecting ? 'Rejecting...' : 'Confirm Rejection'}
            </button>
          )}

          <button
            className="btn btn-primary btn-sm"
            onClick={handleApprove}
            disabled={approving}
            data-testid="approve-identity-btn"
          >
            {approving ? 'Approving...' : 'Approve Identity'}
          </button>
        </div>
      </div>
    </div>
  );
}

function DetailRow({ label, value }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: 'var(--space-xs) 0',
        borderBottom: '1px solid var(--color-border)',
        fontSize: '0.85rem',
      }}
    >
      <span style={{ color: 'var(--color-text-muted)', fontWeight: 500 }}>{label}</span>
      <span style={{ color: 'var(--color-text)', textAlign: 'right', maxWidth: '60%' }}>{value}</span>
    </div>
  );
}