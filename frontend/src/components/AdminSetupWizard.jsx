import React, { useState } from 'react';
import BIP39MnemonicScreen from './BIP39MnemonicScreen';

export default function AdminSetupWizard({ onSetupComplete }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [mnemonicWords, setMnemonicWords] = useState(null);
  const [setupComplete, setSetupComplete] = useState(false);

  async function handleSetupAdmin(e) {
    e.preventDefault();
    setError(null);

    if (!username.trim() || !password.trim()) {
      setError('Username and password are required.');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setLoading(true);

    try {
      const res = await fetch('/api/setup/admin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: username.trim(),
          password: password.trim(),
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Setup failed: ${res.status}`);
      }

      const data = await res.json();

      // The backend returns the BIP39 mnemonic as a string or array
      if (data.mnemonic) {
        const words = Array.isArray(data.mnemonic)
          ? data.mnemonic
          : data.mnemonic.split(/\s+/);
        setMnemonicWords(words);
      } else if (data.recovery_key && Array.isArray(data.recovery_key)) {
        setMnemonicWords(data.recovery_key);
      } else if (data.mnemonic_words && Array.isArray(data.mnemonic_words)) {
        setMnemonicWords(data.mnemonic_words);
      } else {
        setMnemonicWords([]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function handleMnemonicConfirmed() {
    setSetupComplete(true);
    if (onSetupComplete) {
      onSetupComplete();
    }
  }

  // ── Step 2: Mnemonic Display ───────────────────────────────────────────
  if (setupComplete) {
    return (
      <div
        className="archival-card text-center"
        style={{ maxWidth: 500, margin: '2rem auto', padding: 'var(--space-xl)' }}
        data-testid="setup-complete"
      >
        <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-md)' }}>
          Setup Complete
        </h3>
        <p className="text-muted">
          Your administrator account has been created. You may now log in to
          the Executor Console.
        </p>
      </div>
    );
  }

  if (mnemonicWords) {
    return (
      <BIP39MnemonicScreen
        mnemonicWords={mnemonicWords}
        onConfirmed={handleMnemonicConfirmed}
      />
    );
  }

  // ── Step 1: Credentials Form ────────────────────────────────────────────
  return (
    <div
      data-testid="admin-setup-wizard"
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
        padding: 'var(--space-lg)',
        background: 'var(--color-bg)',
      }}
    >
      <form
        onSubmit={handleSetupAdmin}
        className="archival-card"
        style={{ maxWidth: 440, width: '100%' }}
        data-testid="setup-creds-form"
      >
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            marginBottom: 'var(--space-md)',
            textAlign: 'center',
          }}
        >
          First-Time Administrator Setup
        </h2>

        <p
          className="text-muted text-sm"
          style={{ marginBottom: 'var(--space-lg)', textAlign: 'center' }}
        >
          Create your executor administrator account. This is a one-time setup.
          Choose a strong password and store your recovery key safely.
        </p>

        {error && (
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
          <div>
            <label className="form-label" htmlFor="setup-username">
              Administrator Username
            </label>
            <input
              id="setup-username"
              className="form-input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="executor"
              autoComplete="username"
              data-testid="setup-username-input"
            />
          </div>
          <div>
            <label className="form-label" htmlFor="setup-password">
              Password (min 8 characters)
            </label>
            <input
              id="setup-password"
              className="form-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              data-testid="setup-password-input"
            />
          </div>
          <button
            className="btn btn-primary btn-lg"
            type="submit"
            disabled={loading}
            style={{ marginTop: 'var(--space-sm)' }}
            data-testid="setup-submit-btn"
          >
            {loading ? 'Creating Account...' : 'Create Administrator Account'}
          </button>
        </div>
      </form>
    </div>
  );
}