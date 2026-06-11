import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function AbstentionWaitScreen() {
  const userStatus = useMediationStore((s) => s.userStatus);
  const downloadWaiverReceipt = useMediationStore((s) => s.downloadWaiverReceipt);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState(null);

  const handleDownload = async () => {
    setDownloading(true);
    setError(null);
    try {
      await downloadWaiverReceipt();
    } catch (err) {
      setError(err.message || 'Failed to download receipt');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="flex items-center justify-center" style={{ flex: 1, padding: 'var(--space-xl)', minHeight: '60vh', display: 'flex' }}>
      <div className="archival-card text-center" style={{ maxWidth: 540, width: '100%', padding: 'var(--space-xl)' }}>
        {userStatus === 'ABSTAINED' ? (
          <>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.5rem', fontWeight: 'bold', marginBottom: 'var(--space-md)' }}>
              Mediation Opt-Out Registered
            </h2>
            <p className="text-muted" style={{ marginBottom: 'var(--space-lg)', lineHeight: 1.6 }}>
              You have voluntarily chosen to abstain from the points allocation process. Your signed waiver has been cryptographically recorded in the audit logs. You are excluded from the division math, and no assets will be allocated to you. You can return to this screen once the session is finalized by the Executor to download the final Keepsake Memory Book.
            </p>
            {error && (
              <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
                {error}
              </div>
            )}
            <button
              type="button"
              className="btn"
              onClick={handleDownload}
              disabled={downloading}
              style={{
                border: '1px solid var(--color-text)',
                background: 'none',
                color: 'var(--color-text)',
                padding: 'var(--space-sm) var(--space-lg)',
                fontSize: '0.938rem',
                cursor: 'pointer',
                borderRadius: 'var(--radius-md)',
              }}
              data-testid="download-receipt-btn"
            >
              {downloading ? 'Downloading...' : 'Download Signed Waiver Receipt (PDF)'}
            </button>
          </>
        ) : (
          <>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.5rem', fontWeight: 'bold', marginBottom: 'var(--space-md)' }}>
              Invitation Link Expired
            </h2>
            <p className="text-muted" style={{ marginBottom: 'var(--space-lg)', lineHeight: 1.6 }}>
              The invitation link for this mediation session has expired. If you did not intend to opt out or need to request a new link, please contact the Executor of the estate directly.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
