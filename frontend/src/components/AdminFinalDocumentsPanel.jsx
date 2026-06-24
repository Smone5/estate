import React, { useMemo, useState } from 'react';

function safeFilePart(value, fallback) {
  const cleaned = String(value || '')
    .trim()
    .replace(/[^a-z0-9_-]+/gi, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
  return cleaned || fallback;
}

async function downloadPdf({ url, filename }) {
  const res = await fetch(url, { credentials: 'same-origin' });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Download failed: ${res.status}`);
  }

  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(objectUrl);
}

export default function AdminFinalDocumentsPanel({ sessionId, sessionTitle, heirs = [] }) {
  const [busyKey, setBusyKey] = useState(null);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const heirRows = useMemo(
    () => heirs.filter((heir) => (heir.role || 'HEIR') === 'HEIR'),
    [heirs],
  );
  const sessionName = safeFilePart(sessionTitle, 'estate-session');

  async function runDownload(key, action, successMessage) {
    setBusyKey(key);
    setError(null);
    setSuccess(null);
    try {
      await action();
      setSuccess(successMessage);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDownloadLedger() {
    await runDownload(
      'ledger',
      () => downloadPdf({
        url: `/api/sessions/${sessionId}/keepsake`,
        filename: `${sessionName}-probate-audit-ledger.pdf`,
      }),
      'Probate audit ledger downloaded.',
    );
  }

  async function handleDownloadHeir(heir) {
    const heirName = safeFilePart(
      heir.username ||
        `${heir.legal_first_name || ''} ${heir.legal_last_name || ''}`.trim() ||
        heir.email,
      'heir',
    );
    await runDownload(
      `heir-${heir.id}`,
      () => downloadPdf({
        url: `/api/sessions/${sessionId}/heirs/${heir.id}/keepsake`,
        filename: `${sessionName}-${heirName}-keepsake-memory-book.pdf`,
      }),
      `${heir.username || heir.email || 'Heir'} keepsake downloaded.`,
    );
  }

  async function handleDownloadAll() {
    await runDownload(
      'all',
      async () => {
        await downloadPdf({
          url: `/api/sessions/${sessionId}/keepsake/zip`,
          filename: `${sessionName}-all-documents.zip`,
        });
      },
      'All final documents downloaded as a ZIP.',
    );
  }

  const isBusy = Boolean(busyKey);

  return (
    <div className="archival-card" data-testid="admin-final-documents-panel">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 'var(--space-md)',
          flexWrap: 'wrap',
          marginBottom: 'var(--space-md)',
        }}
      >
        <div>
          <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-xs)' }}>
            Final Legal Documents
          </h3>
          <p className="text-muted text-sm" style={{ margin: 0, maxWidth: 620 }}>
            Download the sealed probate audit ledger for court filing and each heir's keepsake memory book for family records.
          </p>
        </div>
        <button
          className="btn btn-primary btn-sm"
          onClick={handleDownloadAll}
          disabled={isBusy}
          data-testid="download-all-final-documents-btn"
        >
          {busyKey === 'all' ? 'Preparing PDFs...' : 'Download All PDFs'}
        </button>
      </div>

      {error && (
        <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
          {error}
        </div>
      )}
      {success && (
        <div className="banner banner-success" style={{ marginBottom: 'var(--space-md)' }}>
          {success}
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) auto',
          gap: 'var(--space-sm)',
          alignItems: 'center',
          borderTop: '1px solid var(--color-border)',
          paddingTop: 'var(--space-md)',
        }}
      >
        <div>
          <strong>Final Distribution & Probate Audit Ledger</strong>
          <p className="text-muted text-xs" style={{ margin: '2px 0 0' }}>
            Sealed allocation record, audit chain, notice log, and court filing summary.
          </p>
        </div>
        <button
          className="btn btn-secondary btn-sm"
          onClick={handleDownloadLedger}
          disabled={isBusy}
          data-testid="download-probate-ledger-btn"
        >
          {busyKey === 'ledger' ? 'Downloading...' : 'Download PDF'}
        </button>

        {heirRows.map((heir) => {
          const label =
            heir.username ||
            `${heir.legal_first_name || ''} ${heir.legal_last_name || ''}`.trim() ||
            heir.email ||
            'Heir';
          return (
            <React.Fragment key={heir.id}>
              <div>
                <strong>{label} Keepsake Memory Book</strong>
                <p className="text-muted text-xs" style={{ margin: '2px 0 0' }}>
                  Final heir copy with allocated keepsakes and shared memory summaries.
                </p>
              </div>
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => handleDownloadHeir(heir)}
                disabled={isBusy}
                data-testid={`download-heir-keepsake-${heir.id}`}
              >
                {busyKey === `heir-${heir.id}` ? 'Downloading...' : 'Download PDF'}
              </button>
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
