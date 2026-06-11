import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMediationStore } from '../store/useMediationStore';

export default function InvitePage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const store = useMediationStore();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [inviteUsed, setInviteUsed] = useState(false);
  const [resuming, setResuming] = useState(false);

  // Onboarding state
  const [legalProfileConfirmed, setLegalProfileConfirmed] = useState(false);
  const [ageConsent, setAgeConsent] = useState(false);
  const [executorAck, setExecutorAck] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Pre-filled legal profile (editable)
  const [legalFirstName, setLegalFirstName] = useState('');
  const [legalMiddleName, setLegalMiddleName] = useState('');
  const [legalLastName, setLegalLastName] = useState('');
  const [relationship, setRelationship] = useState('');
  const [dateOfBirth, setDateOfBirth] = useState('');

  const [inviteNames, setInviteNames] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function checkStatus() {
      try {
        const data = await store.checkInviteStatus(token);
        if (cancelled) return;
        setInviteUsed(data.used);
        setInviteNames({
          first: data.legal_first_name || '',
          last: data.legal_last_name || '',
        });
        // Pre-populate legal profile fields from invite status response
        if (!data.used) {
          setLegalFirstName(data.legal_first_name || '');
          setLegalMiddleName(data.legal_middle_name || '');
          setLegalLastName(data.legal_last_name || '');
          setRelationship(data.relationship_to_decedent || '');
          setDateOfBirth(data.date_of_birth || '');
        }
      } catch (err) {
        if (!cancelled) setError('Unable to verify invitation. The link may be invalid or expired.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    checkStatus();
    return () => { cancelled = true; };
  }, [token, store]);

  async function handleResume() {
    setResuming(true);
    try {
      await store.resumeSession(token);
      navigate('/dashboard');
    } catch {
      setError('Session resumption failed. Please contact the Executor.');
      setResuming(false);
    }
  }

  async function handleAccept() {
    setSubmitting(true);
    setError(null);

    try {
      const res = await fetch(`/api/invite/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token,
          consent_accepted: true,
          age_verified: true,
          legal_first_name: legalFirstName,
          legal_middle_name: legalMiddleName || null,
          legal_last_name: legalLastName,
          relationship_to_decedent: relationship,
          date_of_birth: dateOfBirth,
        }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Verification failed (${res.status})`);
      }

      // Update store and redirect
      store.setSession({ isAuthenticated: true });
      navigate('/dashboard');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  function handleDecline() {
    navigate('/opt-out');
  }

  if (loading) {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
        <div className="archival-card text-center" style={{ maxWidth: 480, width: '100%' }}>
          <h2 style={{ marginBottom: 'var(--space-md)' }}>Verifying Invitation</h2>
          <p className="text-muted">Please wait while we validate your invitation link...</p>
        </div>
      </div>
    );
  }

  if (error && !inviteUsed) {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
        <div className="archival-card text-center" style={{ maxWidth: 480, width: '100%' }}>
          <h2 style={{ marginBottom: 'var(--space-md)' }}>Invitation Error</h2>
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
          <p className="text-muted text-sm">
            Please check your invitation link or contact the Executor for a new invitation.
          </p>
        </div>
      </div>
    );
  }

  // ── Session Resumption Card (token already used) ──────────────────────────
  if (inviteUsed) {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1 }}>
        <div className="archival-card text-center" style={{ maxWidth: 480, width: '100%' }}>
          <h2 style={{ marginBottom: 'var(--space-md)' }}>Mediation Workspace Resumption</h2>
          <p style={{ marginBottom: 'var(--space-lg)' }}>
            This invitation has already been verified and onboarding is complete.
            {inviteNames && (
              <> If you are returning to resume your active mediation session as <strong>{inviteNames.first} {inviteNames.last}</strong> (on a new device or after clearing cookies), please click below to enter the workspace without re-accepting consent.</>
            )}
          </p>
          {error && (
            <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
              {error}
            </div>
          )}
          <button
            className="btn btn-primary btn-lg"
            onClick={handleResume}
            disabled={resuming}
          >
            {resuming ? 'Resuming...' : 'Resume Mediation'}
          </button>
        </div>
      </div>
    );
  }

  // ── Onboarding Consent Flow ───────────────────────────────────────────────
  const canAccept = legalProfileConfirmed && ageConsent && executorAck && legalFirstName.trim() && legalLastName.trim();

  return (
    <div className="app-main" style={{ flex: 1, padding: 'var(--space-lg)', overflowY: 'auto' }}>
      <div style={{ maxWidth: 640, margin: '0 auto' }}>
        {/* Privacy & Consent Card */}
        <div className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
          <h2 style={{ marginBottom: 'var(--space-md)' }}>Privacy & Consent Agreement</h2>
          <p style={{ marginBottom: 'var(--space-md)' }} className="text-sm">
            Welcome to The Estate Steward. Before entering the mediation workspace, please review how
            your data is handled:
          </p>
          <ul style={{ paddingLeft: 'var(--space-lg)', marginBottom: 'var(--space-md)', fontSize: '0.875rem', lineHeight: 1.7 }}>
            <li>All chat messages and point valuations are encrypted at rest using AES-256 (Fernet).</li>
            <li>Your text is filtered through Microsoft Presidio to remove personally identifiable information before processing by the local AI models.</li>
            <li>All AI processing runs entirely on local hardware. No data is sent to external cloud services.</li>
            <li>You may export your data at any time, and you have the right to request deletion of your personal information.</li>
          </ul>

          <div className="banner banner-info" style={{ marginBottom: 'var(--space-lg)' }}>
            <strong>CCPA/CPRA Notice:</strong> We do not sell, share, or monetize your personal
            information. All data is processed locally on our self-hosted platform.
          </div>
        </div>

        {/* E-SIGN Act Consumer Disclosure Banner */}
        <div className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
          <h3 style={{ marginBottom: 'var(--space-sm)' }}>E-SIGN Act Consumer Disclosure</h3>
          <div style={{ fontSize: '0.813rem', lineHeight: 1.7 }}>
            <p style={{ marginBottom: 'var(--space-sm)' }}>
              <strong>Electronic Delivery Consent:</strong> All notifications, keepsakes, and legal
              waivers (including the Abstention Waiver) will be delivered electronically.
            </p>
            <p style={{ marginBottom: 'var(--space-sm)' }}>
              <strong>Right to Withdraw Consent:</strong> You may withdraw electronic consent at any
              time without fees, but doing so will require physical service of notices and paper ledger
              filings.
            </p>
            <p style={{ marginBottom: 'var(--space-sm)' }}>
              <strong>Hardware & Software Requirements:</strong> A modern browser (Chrome, Firefox,
              Safari) with PDF reader capability is required.
            </p>
            <p style={{ marginBottom: 'var(--space-sm)' }}>
              <strong>Right to Paper Records:</strong> You have the right to request paper copies of
              all files from the Executor free of charge.
            </p>
          </div>
        </div>

        {/* Legal Profile Summary Card (editable text inputs) */}
        <div className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
          <h3 style={{ marginBottom: 'var(--space-md)' }}>Your Legal Profile</h3>
          <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-md)' }}>
            These details were provided by the Executor. Please review carefully and correct any typos.
            Accurate legal information is required for probate record-keeping.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-md)' }}>
            <div>
              <label className="form-label">Legal First Name *</label>
              <input
                className="form-input"
                type="text"
                value={legalFirstName}
                onChange={(e) => setLegalFirstName(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="form-label">Legal Middle Name</label>
              <input
                className="form-input"
                type="text"
                value={legalMiddleName}
                onChange={(e) => setLegalMiddleName(e.target.value)}
              />
            </div>
          </div>

          <div style={{ marginTop: 'var(--space-md)' }}>
            <label className="form-label">Legal Last Name *</label>
            <input
              className="form-input"
              type="text"
              value={legalLastName}
              onChange={(e) => setLegalLastName(e.target.value)}
              required
            />
          </div>

          {/* Legal profile confirmation checkbox */}
          <div style={{ marginTop: 'var(--space-md)' }}>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={legalProfileConfirmed}
                onChange={(e) => setLegalProfileConfirmed(e.target.checked)}
              />
              <span>These details are correct and match my official identity documents.</span>
            </label>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-md)', marginTop: 'var(--space-md)' }}>
            <div>
              <label className="form-label">Relationship to Decedent *</label>
              <input
                className="form-input"
                type="text"
                value={relationship}
                onChange={(e) => setRelationship(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="form-label">Date of Birth *</label>
              <input
                className="form-input"
                type="date"
                value={dateOfBirth}
                onChange={(e) => setDateOfBirth(e.target.value)}
                required
              />
            </div>
          </div>
        </div>

        {/* Executor Acknowledgment */}
        <div className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
          <h3 style={{ marginBottom: 'var(--space-sm)' }}>Executor Acknowledgment</h3>
          <p className="text-sm" style={{ marginBottom: 'var(--space-md)' }}>
            The Estate Steward's algorithm provides advisory allocation recommendations. The
            Executor retains sole fiduciary authority to accept, reject, or override any suggested
            distribution. Final asset division is subject to probate court approval and does not
            constitute binding legal judgment.
          </p>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={executorAck}
              onChange={(e) => setExecutorAck(e.target.checked)}
            />
            <span>I understand that the AI Mediator's allocation results are advisory only, and
            the Executor has final decision-making authority.</span>
          </label>
        </div>

        {/* Age Gate & Consent Checkbox */}
        <div className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={ageConsent}
              onChange={(e) => setAgeConsent(e.target.checked)}
            />
            <span>I confirm that I am at least 18 years of age, verify that my legal profile is
            correct, and explicitly agree to the Privacy Policy and E-SIGN Electronic Records
            Disclosure.</span>
          </label>
        </div>

        {/* Error display */}
        {error && (
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-md" style={{ marginBottom: 'var(--space-2xl)' }}>
          <button
            className="btn btn-primary btn-lg"
            onClick={handleAccept}
            disabled={!canAccept || submitting}
            style={{ flex: 1 }}
          >
            {submitting ? 'Processing...' : 'Accept & Enter Workspace'}
          </button>
          <button
            className="btn btn-secondary btn-lg"
            onClick={handleDecline}
            disabled={submitting}
          >
            Decline & Exit
          </button>
        </div>
      </div>
    </div>
  );
}