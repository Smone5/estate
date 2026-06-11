import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function AbstentionWaiverModal({ onClose }) {
  const legalFirstName = useMediationStore((s) => s.legal_first_name) || '';
  const legalMiddleName = useMediationStore((s) => s.legal_middle_name) || '';
  const legalLastName = useMediationStore((s) => s.legal_last_name) || '';
  const abstainSession = useMediationStore((s) => s.abstainSession);

  const [signature, setSignature] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  // Construct expected legal name dynamically per UI spec §8.8
  const parts = [legalFirstName, legalMiddleName, legalLastName].filter(
    (name) => name !== null && name !== undefined && name !== 'None' && name !== 'null' && name.trim() !== ''
  );
  const expectedName = parts.join(' ').trim();

  const handleAbstain = async () => {
    if (signature !== expectedName || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await abstainSession(signature);
      onClose();
    } catch (err) {
      setError(err.message || 'Abstention request failed');
      setSubmitting(false);
    }
  };

  const isMatched = signature === expectedName;

  const signatureInputStyle = {
    border: 'none',
    borderBottom: isFocused ? '2px solid var(--color-primary)' : '1px solid var(--color-border)',
    backgroundColor: 'transparent',
    width: '100%',
    padding: '8px 0',
    fontSize: '1rem',
    outline: 'none',
    fontFamily: 'var(--font-sans)',
    transition: 'border-bottom-color 300ms ease-in-out',
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(30, 41, 59, 0.4)',
        backdropFilter: 'blur(4px)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'var(--space-md)',
      }}
      data-testid="abstention-modal-backdrop"
      onClick={onClose}
    >
      <div
        className="archival-card"
        style={{
          maxWidth: 500,
          width: '100%',
          backgroundColor: 'var(--color-card-bg)',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
          position: 'relative',
        }}
        onClick={(e) => e.stopPropagation()}
        data-testid="abstention-modal-content"
      >
        <h3
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: '1.25rem',
            fontWeight: 'bold',
            marginBottom: 'var(--space-md)',
          }}
        >
          Waiver of Allocation Rights
        </h3>

        <div
          style={{
            border: '1px solid var(--color-border)',
            backgroundColor: 'var(--color-primary-light)',
            padding: 'var(--space-md)',
            borderRadius: 'var(--radius-md)',
            marginBottom: 'var(--space-md)',
          }}
        >
          <p
            className="text-sm"
            style={{
              margin: 0,
              fontStyle: 'italic',
              lineHeight: 1.6,
              color: 'var(--color-text)',
            }}
          >
            "I, <strong>{expectedName}</strong>, hereby voluntarily abstain from the points allocation process and waive all rights to claim physical assets through the digital mediation system. I consent to having the remaining assets distributed among the participating heirs."
          </p>
        </div>

        <div style={{ marginBottom: 'var(--space-lg)' }}>
          <label
            className="form-label"
            style={{
              display: 'block',
              fontSize: '0.875rem',
              fontWeight: 500,
              marginBottom: 'var(--space-xs)',
            }}
          >
            To confirm, please type your full legal name below:
          </label>
          <input
            type="text"
            className="signature-input"
            value={signature}
            onChange={(e) => setSignature(e.target.value)}
            placeholder={expectedName}
            disabled={submitting}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            style={signatureInputStyle}
            data-testid="signature-input"
          />
        </div>

        {error && (
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-sm)' }}>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-secondary"
            disabled={submitting}
            data-testid="cancel-abstain-btn"
          >
            Cancel & Return
          </button>
          <button
            type="button"
            onClick={handleAbstain}
            disabled={!isMatched || submitting}
            className="btn"
            style={{
              backgroundColor: isMatched ? '#F59E0B' : 'var(--color-border)',
              color: isMatched ? '#FFFFFF' : 'var(--color-text-muted)',
              cursor: isMatched && !submitting ? 'pointer' : 'not-allowed',
            }}
            data-testid="confirm-abstain-btn"
          >
            {submitting ? 'Signing...' : 'Sign & Abstain'}
          </button>
        </div>
      </div>
    </div>
  );
}
