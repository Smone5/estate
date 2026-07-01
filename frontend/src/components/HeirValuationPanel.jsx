import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import AbstentionWaiverModal from './AbstentionWaiverModal';
import GDPRDataExportButton from './GDPRDataExportButton';
import GDPRDeleteAccountDrawer from './GDPRDeleteAccountDrawer';

export default function HeirValuationPanel() {
  const unallocatedPoints = useMediationStore((s) => s.unallocatedPoints);
  const isSubmitted = useMediationStore((s) => s.isSubmitted);
  const sessionStatus = useMediationStore((s) => s.sessionStatus);
  const submitValuations = useMediationStore((s) => s.submitValuations);
  const inventoryUpdatedNotice = useMediationStore((s) => s.inventoryUpdatedNotice);
  const practiceCompletedAt = useMediationStore((s) => s.practiceCompletedAt);
  const practiceRequired = useMediationStore((s) => s.practiceRequired);
  const simulationPublishedAt = useMediationStore((s) => s.simulationPublishedAt);

  const [isWaiverOpen, setIsWaiverOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = async () => {
    if (unallocatedPoints !== 0 || isSubmitted || sessionStatus !== 'ACTIVE') return;
    setSubmitting(true);
    setError(null);
    try {
      await submitValuations();
    } catch (err) {
      setError(err.message || 'Failed to submit valuations');
    } finally {
      setSubmitting(false);
    }
  };

  const userRole = useMediationStore((s) => s.userRole);
  const isHeir = userRole === 'HEIR';

  // Only show valuations control panel if session is not finalized/setup
  const showPanel = sessionStatus === 'ACTIVE' || sessionStatus === 'LOCKED';

  // Always render the export button for authenticated heirs
  if (!showPanel) {
    if (!isHeir) return null;
    return (
      <div className="archival-card" style={{ marginBottom: 'var(--space-md)', padding: 'var(--space-md)' }}>
        {sessionStatus === 'SETUP' && (
          <div className="heir-practice-step">
            <span className={practiceCompletedAt ? 'is-complete' : ''}>{practiceCompletedAt ? '✓' : '1'}</span>
            <div>
              <h3>Practice the allocation process</h3>
              <p>
                {practiceCompletedAt
                  ? 'Practice complete. The Executor can now see that you finished; your practice points remain private.'
                  : simulationPublishedAt
                    ? 'Use fictional items to experience the same catalog, 1,000-point review, submission, waiting, and result flow before the real allocation opens.'
                    : 'The Executor is preparing your fictional practice allocation. It will appear here before the real session opens.'}
              </p>
              {practiceRequired && !practiceCompletedAt && <small>Required before the real allocation can launch</small>}
            </div>
            {simulationPublishedAt && (
              <a className="btn btn-primary" href="/allocation-practice">
                {practiceCompletedAt ? 'Practice again' : 'Start required practice'}
              </a>
            )}
          </div>
        )}
        <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.25rem', margin: 'var(--space-lg) 0 var(--space-sm)' }}>
          Data & Settings
        </h3>
        <GDPRDataExportButton />
      </div>
    );
  }

  const canSubmit = unallocatedPoints === 0 && !isSubmitted && sessionStatus === 'ACTIVE';
  const canAbstain = sessionStatus === 'ACTIVE'; // active, even if submitted

  return (
    <div className="archival-card" style={{ marginBottom: 'var(--space-md)', padding: 'var(--space-md)' }}>
      {inventoryUpdatedNotice && (
        <div
          className="banner banner-amber"
          data-testid="inventory-update-warning-banner"
          style={{
            marginBottom: 'var(--space-md)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 'var(--space-sm)',
            flexWrap: 'wrap',
          }}
        >
          <span>
            {inventoryUpdatedNotice} Your submission status has been reset so you can review the updated catalog.
          </span>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => useMediationStore.setState({ inventoryUpdatedNotice: null })}
          >
            Dismiss
          </button>
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-md)' }}>
        <div>
          <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.25rem', marginBottom: '4px' }}>
            Valuation Status
          </h3>
          <p className="text-sm text-muted" style={{ marginBottom: 0 }}>
            {isSubmitted ? (
              <span style={{ color: 'var(--color-primary)', fontWeight: 'bold' }}>✓ Valuations Submitted & Locked</span>
            ) : (
              <>
                Remaining points: <strong className="tabular-value" data-testid="unallocated-points-val">{unallocatedPoints}</strong> / 1000.
                {unallocatedPoints > 0 ? ' Allocate all points to enable submission.' : ' Ready to submit.'}
              </>
            )}
          </p>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
          {!isSubmitted && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleSubmit}
              disabled={!canSubmit || submitting}
              data-testid="submit-valuations-btn"
            >
              {submitting ? 'Submitting...' : 'Submit Valuations'}
            </button>
          )}

          <button
            type="button"
            className="btn"
            onClick={() => setIsWaiverOpen(true)}
            disabled={!canAbstain}
            style={{
              border: '1px solid var(--color-text)',
              background: 'none',
              color: 'var(--color-text)',
              cursor: canAbstain ? 'pointer' : 'not-allowed',
              opacity: canAbstain ? 1 : 0.5,
            }}
            data-testid="abstain-trigger-btn"
          >
            Abstain & Waive Allocation Rights
          </button>
        </div>
      </div>

      {error && (
        <div className="banner banner-error" style={{ marginTop: 'var(--space-md)', marginBottom: 0 }}>
          {error}
        </div>
      )}

      {isWaiverOpen && (
        <AbstentionWaiverModal onClose={() => setIsWaiverOpen(false)} />
      )}

      <div style={{ marginTop: 'var(--space-lg)', paddingTop: 'var(--space-md)', borderTop: '1px solid var(--color-border)', display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
        <a className="btn btn-secondary" href="/allocation-practice">
          Practice with sample items
        </a>
        <GDPRDataExportButton />
        <GDPRDeleteAccountDrawer />
      </div>
    </div>
  );
}
