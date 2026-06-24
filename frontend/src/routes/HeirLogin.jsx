import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMediationStore } from '../store/useMediationStore';

export default function HeirLoginPage() {
  const navigate = useNavigate();
  const heirPasswordLogin = useMediationStore((s) => s.heirPasswordLogin);
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await heirPasswordLogin({
        identifier: identifier.trim(),
        password,
      });
      navigate('/dashboard');
    } catch (err) {
      setError(err.message || 'Unable to sign in. Please verify your credentials.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
      <form className="archival-card" style={{ maxWidth: 440, width: '100%' }} onSubmit={handleSubmit}>
        <h2 style={{ marginBottom: 'var(--space-sm)' }}>Heir Sign In</h2>
        <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-lg)' }}>
          Use the email address or display name on your invitation, plus the password
          you created during onboarding.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
          <div>
            <label className="form-label" htmlFor="heir-login-identifier">
              Email or Display Name
            </label>
            <input
              id="heir-login-identifier"
              className="form-input"
              type="text"
              autoComplete="username"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="form-label" htmlFor="heir-login-password">
              Password
            </label>
            <input
              id="heir-login-password"
              className="form-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
        </div>

        {error && (
          <div className="banner banner-error" style={{ marginTop: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary btn-lg"
          disabled={!identifier.trim() || !password || submitting}
          style={{ width: '100%', marginTop: 'var(--space-lg)' }}
        >
          {submitting ? 'Signing In...' : 'Sign In'}
        </button>
      </form>
    </div>
  );
}
