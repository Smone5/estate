import React, { useState, useRef } from 'react';

export default function BIP39RestorePanel() {
  const [recoveryWords, setRecoveryWords] = useState('');
  const [restoring, setRestoring] = useState(false);
  const [downloadingBackup, setDownloadingBackup] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [restoreProgress, setRestoreProgress] = useState(false);
  const restoreFileRef = useRef(null);

  // ── Validate word count ──────────────────────────────────────────────────
  function parseWords(input) {
    return input
      .trim()
      .split(/\s+/)
      .filter((w) => w.length > 0);
  }

  // ── Download Backup ────────────────────────────────────────────────────
  async function handleDownloadBackup() {
    setError(null);
    setSuccess(null);
    setDownloadingBackup(true);

    try {
      const res = await fetch('/api/system/backup');
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Backup download failed: ${res.status}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `estate-backup-${new Date().toISOString().slice(0, 10)}.estate.bak`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      setSuccess('System backup downloaded successfully.');
    } catch (err) {
      setError(err.message);
    } finally {
      setDownloadingBackup(false);
    }

    // Clear success after 5s
    setTimeout(() => setSuccess(null), 5000);
  }

  // ── Upload & Restore ───────────────────────────────────────────────────
  function handleRestoreFileSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    performRestore(file);
    e.target.value = '';
  }

  async function performRestore(file) {
    setError(null);
    setSuccess(null);

    const words = parseWords(recoveryWords);
    const hasRecoveryKey = words.length > 0;

    if (hasRecoveryKey && words.length !== 24) {
      setError('Paper Recovery Key must be exactly 24 words if provided.');
      return;
    }

    setRestoring(true);
    setRestoreProgress(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      if (hasRecoveryKey) {
        formData.append('recovery_key', words.join(' '));
      }

      const res = await fetch('/api/system/restore', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Restore failed: ${res.status}`);
      }

      const data = await res.json();
      setSuccess(
        'System restore successful. Please reload the page to refresh the active session state.',
      );
      setRecoveryWords('');

      // Prompt page reload after 2s
      setTimeout(() => {
        window.location.reload();
      }, 2000);
    } catch (err) {
      setError(err.message);
    } finally {
      setRestoring(false);
      setRestoreProgress(false);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────
  const wordCount = parseWords(recoveryWords).length;

  return (
    <div className="archival-card" data-testid="bip39-restore-panel">
      {/* Divider header */}
      <div
        style={{
          borderTop: '2px solid var(--color-border)',
          paddingTop: 'var(--space-lg)',
          marginTop: 'var(--space-lg)',
          marginBottom: 'var(--space-md)',
        }}
      >
        <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: '4px' }}>
          System Backup & Disaster Recovery
        </h3>
        <p className="text-muted text-sm">
          Download encrypted database backups or restore from a previously saved
          <code>.estate.bak</code> archive.
        </p>
      </div>

      {/* Error / Success banners */}
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

      {/* Progress overlay */}
      {restoreProgress && (
        <div
          data-testid="restore-progress-overlay"
          className="archival-card"
          style={{
            textAlign: 'center',
            padding: 'var(--space-xl)',
            marginBottom: 'var(--space-md)',
            background: 'var(--color-primary-light)',
          }}
        >
          <p style={{ fontWeight: 600 }}>
            Restoring system state... please do not close or refresh this page.
          </p>
        </div>
      )}

      {/* Download Backup */}
      <div style={{ marginBottom: 'var(--space-lg)' }}>
        <h4 style={{ marginBottom: 'var(--space-sm)' }}>Generate System Backup</h4>
        <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-sm)' }}>
          Download a Fernet-encrypted <code>.estate.bak</code> archive containing
          the complete database state. Store this file securely offline.
        </p>
        <button
          className="btn btn-primary btn-sm"
          onClick={handleDownloadBackup}
          disabled={downloadingBackup}
          data-testid="download-backup-btn"
        >
          {downloadingBackup ? 'Generating Backup...' : 'Download Backup (.estate.bak)'}
        </button>
      </div>

      {/* Restore */}
      <div>
        <h4 style={{ marginBottom: 'var(--space-sm)' }}>Upload & Restore Backup</h4>
        <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-md)' }}>
          Select a <code>.estate.bak</code> file to restore. If restoring on a fresh
          system, provide your 24-word Paper Recovery Key to decrypt the backup.
        </p>

        {/* Paper Recovery Key Input */}
        <div style={{ marginBottom: 'var(--space-md)' }}>
          <label className="form-label" htmlFor="recovery-key-input">
            Paper Recovery Key (Optional — required for fresh system restore)
          </label>
          <textarea
            id="recovery-key-input"
            className="form-input"
            value={recoveryWords}
            onChange={(e) => setRecoveryWords(e.target.value)}
            rows={4}
            placeholder="Enter your 24-word BIP39 mnemonic recovery phrase, one word per line or space-separated..."
            style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}
            data-testid="recovery-key-textarea"
          />
          <p
            className="text-sm"
            data-testid="word-count-indicator"
            style={{
              marginTop: '4px',
              color: wordCount > 0 && wordCount !== 24 ? 'var(--color-alert)' : 'var(--color-text-muted)',
            }}
          >
            {wordCount > 0
              ? `${wordCount} of 24 words entered`
              : 'Leave blank if restoring to the same system'}
          </p>
        </div>

        {/* Restore file selector */}
        <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
          <button
            className="btn btn-primary btn-sm"
            style={{
              background: 'var(--color-alert)',
              borderColor: 'var(--color-alert)',
            }}
            onClick={() => restoreFileRef.current?.click()}
            disabled={restoring}
            data-testid="upload-restore-btn"
          >
            {restoring ? 'Restoring...' : 'Upload & Restore Backup'}
          </button>
          <input
            ref={restoreFileRef}
            type="file"
            accept=".estate.bak,.bak"
            style={{ display: 'none' }}
            onChange={handleRestoreFileSelect}
            data-testid="restore-file-input"
          />
        </div>
      </div>
    </div>
  );
}