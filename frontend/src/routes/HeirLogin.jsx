import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMediationStore } from '../store/useMediationStore';

export default function HeirLoginPage() {
  const navigate = useNavigate();
  const heirPasswordLogin = useMediationStore((s) => s.heirPasswordLogin);
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [sessionChoices, setSessionChoices] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const data = await heirPasswordLogin({
        identifier: identifier.trim(),
        password,
      });
      if (data?.status === 'multiple_sessions') {
        setSessionChoices(data.sessions);
        return;
      }
      navigate('/dashboard');
    } catch (err) {
      setError(err.message || 'Unable to sign in. Please verify your credentials.');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleChooseSession(sessionId) {
    setSubmitting(true);
    setError(null);

    try {
      await heirPasswordLogin({
        identifier: identifier.trim(),
        password,
        session_id: sessionId,
      });
      navigate('/dashboard');
    } catch (err) {
      setError(err.message || 'Unable to sign in. Please verify your credentials.');
      setSessionChoices(null);
    } finally {
      setSubmitting(false);
    }
  }

  if (sessionChoices) {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
        <div className="archival-card" style={{ maxWidth: 440, width: '100%' }}>
          <h2 style={{ marginBottom: 'var(--space-sm)' }}>Choose an Estate</h2>
          <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-lg)' }}>
            Your credentials match more than one mediation session. Select the estate you
            would like to enter.
          </p>

          {error && (
            <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
            {sessionChoices.map((s) => (
              <button
                key={s.session_id}
                type="button"
                className="btn btn-secondary"
                disabled={submitting}
                onClick={() => handleChooseSession(s.session_id)}
                style={{ textAlign: 'left' }}
              >
                {s.title}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="btn btn-link"
            style={{ marginTop: 'var(--space-md)' }}
            onClick={() => setSessionChoices(null)}
            disabled={submitting}
          >
            Back
          </button>
        </div>
      </div>
    );
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

        <div className="login-practice-link">
          <span>Want to understand the point system first?</span>
          <Link to="/allocation-practice">Try the allocation practice room</Link>
        </div>
      </form>
    </div>
  );
}
