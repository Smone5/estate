import React, { useState } from 'react';

export default function GDPRDataExportButton() {
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);

  async function handleExport() {
    setExporting(true);
    setError(null);

    try {
      const res = await fetch('/api/heirs/me/export');
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Export failed: ${res.status}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `estate-data-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div data-testid="gdpr-export-button-container">
      <button
        className="btn btn-secondary btn-sm"
        onClick={handleExport}
        disabled={exporting}
        data-testid="export-my-data-btn"
        style={{ width: '100%' }}
      >
        {exporting ? 'Exporting...' : 'Export My Data (JSON)'}
      </button>
      {error && (
        <p
          className="text-sm"
          data-testid="export-error"
          style={{ color: 'var(--color-alert)', marginTop: '4px' }}
        >
          {error}
        </p>
      )}
    </div>
  );
}