import React, { useState } from 'react';

export default function BIP39MnemonicScreen({ mnemonicWords, onConfirmed }) {
  const [confirmed, setConfirmed] = useState(false);

  const words = Array.isArray(mnemonicWords) ? mnemonicWords : [];
  const wordCount = words.length;

  // Build 3-column grid rows
  const rows = [];
  for (let i = 0; i < wordCount; i += 3) {
    rows.push(words.slice(i, i + 3));
  }

  function handleConfirm() {
    if (confirmed && onConfirmed) {
      onConfirmed();
    }
  }

  return (
    <div
      className="bip39-mnemonic-screen"
      data-testid="bip39-mnemonic-screen"
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        padding: 'var(--space-lg)',
        background: 'var(--color-bg)',
      }}
    >
      <div className="archival-card" style={{ maxWidth: 600, width: '100%' }}>
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: '1.5rem',
            marginBottom: 'var(--space-md)',
            textAlign: 'center',
          }}
        >
          Administrative Setup & Recovery Key
        </h2>

        <p
          className="text-muted text-sm"
          style={{ marginBottom: 'var(--space-lg)', textAlign: 'center' }}
        >
          Your 24-word Paper Recovery Key is the only way to restore encrypted
          backups if your host device fails. Store it securely offline.
        </p>

        {/* Mnemonic Word Grid */}
        <div
          data-testid="mnemonic-grid"
          style={{
            background: '#F5F5F5',
            border: '2px dashed var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-lg)',
            marginBottom: 'var(--space-lg)',
            fontFamily: 'monospace',
          }}
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: 'var(--space-sm) var(--space-md)',
            }}
          >
            {words.map((word, idx) => (
              <div
                key={idx}
                data-testid={`mnemonic-word-${idx}`}
                style={{
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'center',
                  fontSize: '0.9rem',
                  color: 'var(--color-text)',
                  fontWeight: 500,
                }}
              >
                <span
                  style={{
                    color: 'var(--color-text-muted)',
                    fontSize: '0.7rem',
                    minWidth: '24px',
                    textAlign: 'right',
                  }}
                >
                  {idx + 1}.
                </span>
                <span>{word}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Warning Banner */}
        <div
          data-testid="mnemonic-warning"
          style={{
            background: 'var(--color-alert-light)',
            border: '1px solid var(--color-alert)',
            borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-md)',
            marginBottom: 'var(--space-lg)',
            fontSize: '0.85rem',
            color: 'var(--color-text)',
            fontWeight: 500,
          }}
        >
          <strong>⚠️ WARNING:</strong> Store this key offline in a secure
          physical location (such as a safe). If your host device fails, this
          24-word key is the <strong>ONLY</strong> way to decrypt and restore
          your backups. If lost, your backups are permanently unrecoverable.
        </div>

        {/* Confirmation Checkbox */}
        <div
          style={{
            marginBottom: 'var(--space-lg)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 'var(--space-sm)',
          }}
        >
          <input
            type="checkbox"
            id="mnemonic-confirm"
            data-testid="mnemonic-confirm-checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            style={{ marginTop: '2px' }}
          />
          <label
            htmlFor="mnemonic-confirm"
            style={{ fontSize: '0.85rem', color: 'var(--color-text)' }}
          >
            I have copied and verified my 24-word Paper Recovery Key and
            understand it cannot be recovered if lost.
          </label>
        </div>

        {/* Proceed Button */}
        <button
          className="btn btn-primary btn-lg"
          data-testid="mnemonic-proceed-btn"
          disabled={!confirmed}
          onClick={handleConfirm}
          style={{ width: '100%' }}
        >
          Proceed to Console
        </button>
      </div>
    </div>
  );
}