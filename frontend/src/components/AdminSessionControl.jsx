import React, { useState, useEffect, useCallback } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import AdminInspectIDModal from './AdminInspectIDModal';
import { customConfirm } from '../store/useDialogStore';

const emptyRegistrationForm = {
  username: '',
  email: '',
  phone: '',
  address_line1: '',
  address_line2: '',
  address_city: '',
  address_region: '',
  address_postal_code: '',
  address_country: 'United States',
};

function composeAddress(address) {
  const locality = [address.address_city, address.address_region]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(', ');
  const localityWithPostal = [locality, address.address_postal_code?.trim()]
    .filter(Boolean)
    .join(' ');

  return [
    address.address_line1,
    address.address_line2,
    localityWithPostal,
    address.address_country,
  ]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(', ');
}

function buildInviteUrl(inviteToken) {
  if (!inviteToken) return '';
  const origin = window.location?.origin || 'http://localhost';
  return `${origin}/invite/${inviteToken}`;
}

function buildInviteClipboardText(heir) {
  const heirName =
    heir.username ||
    `${heir.legal_first_name || ''} ${heir.legal_last_name || ''}`.trim() ||
    'Beneficiary';
  const inviteUrl = buildInviteUrl(heir.invite_token);
  const expires = heir.invite_token_expires_at
    ? new Date(heir.invite_token_expires_at).toLocaleString()
    : 'the date provided by the executor';

  return [
    `To: ${heir.email || ''}`,
    'Subject: Estate Mediation Invitation',
    '',
    `Dear ${heirName},`,
    '',
    'You have been invited to participate in an estate keepsake mediation using The Estate Steward.',
    '',
    'Please open this invitation link to review the estate catalog, complete your onboarding, and participate:',
    inviteUrl,
    '',
    `This invitation expires on ${expires}.`,
    '',
    'The Estate Steward',
  ].join('\n');
}

export default function AdminSessionControl({
  sessionId,
  heirs: propHeirs,
  onRefreshHeirs,
}) {
  const sessionStatus = useMediationStore((s) => s.sessionStatus);

  const [internalHeirs, setInternalHeirs] = useState([]);
  const [loading, setLoading] = useState(propHeirs === undefined);
  const [actionError, setActionError] = useState(null);
  const [actionSuccess, setActionSuccess] = useState(null);
  const [selectedIdentityHeir, setSelectedIdentityHeir] = useState(null);
  const [heirOverrides, setHeirOverrides] = useState({});

  const baseHeirs = propHeirs !== undefined ? propHeirs : internalHeirs;
  const heirs = baseHeirs.map((heir) => (
    heirOverrides[heir.id] ? { ...heir, ...heirOverrides[heir.id] } : heir
  ));
  const identityReviewHeirs = heirs.filter(
    (heir) => (heir.status === 'PROFILE_HOLD' || heir.user_status === 'PROFILE_HOLD') && heir.id_scan_uri,
  );

  // Registration form
  const [regForm, setRegForm] = useState(emptyRegistrationForm);
  const [registering, setRegistering] = useState(false);

  // ── Fetch heirs ─────────────────────────────────────────────────────────
  const fetchHeirs = useCallback(async () => {
    if (!sessionId) return;
    if (onRefreshHeirs) {
      await onRefreshHeirs();
      return;
    }
    try {
      setLoading(true);
      const res = await fetch(`/api/sessions/${sessionId}/heirs`, {
        credentials: 'same-origin',
      });
      if (res.ok) {
        const data = await res.json();
        setInternalHeirs(Array.isArray(data) ? data : []);
        setHeirOverrides({});
      } else if (res.status === 401) {
        setActionError('Your session has expired. Please refresh the page to log in again.');
      }
    } catch (err) {
      console.error('Failed to fetch heirs', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, onRefreshHeirs]);

  async function handleVerificationComplete(updatedHeir) {
    if (updatedHeir?.id) {
      setHeirOverrides((current) => ({
        ...current,
        [updatedHeir.id]: updatedHeir,
      }));
      setSelectedIdentityHeir((current) => (
        current?.id === updatedHeir.id ? { ...current, ...updatedHeir } : current
      ));
    }
    setActionSuccess('Identity verification updated.');
    await fetchHeirs();
  }

  useEffect(() => {
    if (propHeirs === undefined) {
      fetchHeirs();
    }
  }, [fetchHeirs, propHeirs]);

  // Clear action messages after timeout
  useEffect(() => {
    if (actionError || actionSuccess) {
      const timer = setTimeout(() => {
        setActionError(null);
        setActionSuccess(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [actionError, actionSuccess]);

  // ── Register Heir ───────────────────────────────────────────────────────
  async function handleRegisterHeir(e) {
    e.preventDefault();
    if (!regForm.username.trim() || !regForm.email.trim()) {
      setActionError('Display Name and Email are required.');
      return;
    }

    setRegistering(true);
    setActionError(null);
    setActionSuccess(null);

    try {
      const physicalAddress = composeAddress(regForm);
      const structuredAddress = {
        address_line1: regForm.address_line1.trim() || null,
        address_line2: regForm.address_line2.trim() || null,
        address_city: regForm.address_city.trim() || null,
        address_region: regForm.address_region.trim() || null,
        address_postal_code: regForm.address_postal_code.trim() || null,
        address_country: regForm.address_country.trim() || null,
      };

      const res = await fetch(`/api/sessions/${sessionId}/heirs`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: regForm.username.trim(),
          email: regForm.email.trim(),
          phone: regForm.phone.trim() || null,
          physical_address: physicalAddress || null,
          ...structuredAddress,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Registration failed: ${res.status}`);
      }

      const createdHeir = await res.json().catch(() => ({}));
      const createdHeirId = createdHeir.id || createdHeir.heir_id;
      let inviteDispatched = false;
      let inviteError = null;

      if (createdHeirId && regForm.email.trim()) {
        const inviteRes = await fetch(`/api/heirs/${createdHeirId}/send-invite`, {
          method: 'POST',
          credentials: 'same-origin',
        });
        if (inviteRes.ok) {
          inviteDispatched = true;
        } else {
          const errData = await inviteRes.json().catch(() => ({}));
          inviteError = errData.detail || `Invite email failed: ${inviteRes.status}`;
        }
      }

      setRegForm(emptyRegistrationForm);
      if (inviteDispatched) {
        setActionSuccess('Heir registered and invitation email sent.');
      } else if (inviteError) {
        setActionSuccess(`Heir registered, but invitation email was not sent: ${inviteError}`);
      } else {
        setActionSuccess('Heir registered successfully.');
      }
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    } finally {
      setRegistering(false);
    }
  }

  // ── Send Invite ─────────────────────────────────────────────────────────
  async function handleSendInvite(heirId) {
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/heirs/${heirId}/send-invite`, {
        method: 'POST',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Send invite failed: ${res.status}`);
      }
      setActionSuccess('Invitation email dispatched.');
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    }
  }

  // ── Regenerate Token ────────────────────────────────────────────────────
  async function handleRegenerateToken(heirId) {
    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/heirs/${heirId}/invite-token`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Token regeneration failed: ${res.status}`);
      }
      setActionSuccess('Invite token regenerated.');
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    }
  }

  // ── Copy Token to Clipboard ─────────────────────────────────────────────
  function handleCopyToken(token) {
    navigator.clipboard.writeText(token).then(
      () => setActionSuccess('Token copied to clipboard.'),
      () => setActionError('Failed to copy token.'),
    );
  }

  function handleCopyInvite(heir) {
    navigator.clipboard.writeText(buildInviteClipboardText(heir)).then(
      () => setActionSuccess('Invite message copied. Paste it into your email app to send manually.'),
      () => setActionError('Failed to copy invite message.'),
    );
  }

  // ── Delete Heir ─────────────────────────────────────────────────────────
  async function handleDeleteHeir(heirId, heirName) {
    if (!await customConfirm(`Permanently delete heir "${heirName}"? This will purge all PII, chat history, and ID scans. This action cannot be undone.`)) {
      return;
    }

    setActionError(null);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/heirs/${heirId}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Delete heir failed: ${res.status}`);
      }
      setActionSuccess('Heir deleted and PII purged.');
      await fetchHeirs();
    } catch (err) {
      setActionError(err.message);
    }
  }

  // ── Status helpers ──────────────────────────────────────────────────────
  function statusCheckmark(status) {
    if (status === 'SUBMITTED') return '✅';
    if (status === 'ABSTAINED') return '⚪ Abstained';
    if (status === 'EXPIRED_NON_PARTICIPATING') return '⏹ Expired';
    if (status === 'PROFILE_HOLD') return '🆔 ID Hold';
    if (status === 'ACTIVE') return '⏳ Active';
    return '⏳ Pending';
  }

  function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────
  const isSetup = sessionStatus === 'SETUP';

  if (!sessionId) {
    return (
      <div className="archival-card">
        <p className="text-muted">No active session selected.</p>
      </div>
    );
  }

  return (
    <div className="admin-session-control" data-testid="admin-session-control">
      {/* Action feedback */}
      {actionError && (
        <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
          {actionError}
        </div>
      )}
      {actionSuccess && (
        <div className="banner banner-success" style={{ marginBottom: 'var(--space-md)' }}>
          {actionSuccess}
        </div>
      )}

      {identityReviewHeirs.length > 0 && (
        <div
          className="banner banner-amber"
          data-testid="identity-review-banner"
          style={{
            marginBottom: 'var(--space-md)',
            display: 'flex',
            justifyContent: 'space-between',
            gap: 'var(--space-md)',
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <span>
            <strong>{identityReviewHeirs.length} ID review pending.</strong>
            {' '}Inspect uploaded ID documents before launching or continuing mediation.
          </span>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setSelectedIdentityHeir(identityReviewHeirs[0])}
            data-testid="open-first-id-review-btn"
          >
            Review ID
          </button>
        </div>
      )}

      {/* Heir Registration Panel (Setup only) */}
      {isSetup && (
        <div id="register-heir-section" className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
          <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-md)' }}>
            Register Heir
          </h3>
          <form onSubmit={handleRegisterHeir}>
            <div className="admin-form-grid">
              <div>
                <label className="form-label" htmlFor="heir-username">
                  Display Name *
                </label>
                <input
                  id="heir-username"
                  className="form-input"
                  value={regForm.username}
                  onChange={(e) => setRegForm((p) => ({ ...p, username: e.target.value }))}
                  placeholder="e.g. Alice Smith"
                  data-testid="heir-reg-username"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-email">
                  Email Address *
                </label>
                <input
                  id="heir-email"
                  className="form-input"
                  type="email"
                  value={regForm.email}
                  onChange={(e) => setRegForm((p) => ({ ...p, email: e.target.value }))}
                  placeholder="alice@example.com"
                  data-testid="heir-reg-email"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-phone">
                  Phone (optional)
                </label>
                <input
                  id="heir-phone"
                  className="form-input"
                  type="tel"
                  value={regForm.phone}
                  onChange={(e) => setRegForm((p) => ({ ...p, phone: e.target.value }))}
                  placeholder="+1 (555) 123-4567"
                  data-testid="heir-reg-phone"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-address-line1">
                  Address Line 1 (optional)
                </label>
                <input
                  id="heir-address-line1"
                  className="form-input"
                  value={regForm.address_line1}
                  onChange={(e) => setRegForm((p) => ({ ...p, address_line1: e.target.value }))}
                  placeholder="1429 Villa Capri Circle"
                  data-testid="heir-reg-address-line1"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-address-line2">
                  Address Line 2 (optional)
                </label>
                <input
                  id="heir-address-line2"
                  className="form-input"
                  value={regForm.address_line2}
                  onChange={(e) => setRegForm((p) => ({ ...p, address_line2: e.target.value }))}
                  placeholder="Apt, suite, unit, building"
                  data-testid="heir-reg-address-line2"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-address-city">
                  City / Locality (optional)
                </label>
                <input
                  id="heir-address-city"
                  className="form-input"
                  value={regForm.address_city}
                  onChange={(e) => setRegForm((p) => ({ ...p, address_city: e.target.value }))}
                  placeholder="Odessa"
                  data-testid="heir-reg-address-city"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-address-region">
                  State / Province / Region (optional)
                </label>
                <input
                  id="heir-address-region"
                  className="form-input"
                  value={regForm.address_region}
                  onChange={(e) => setRegForm((p) => ({ ...p, address_region: e.target.value }))}
                  placeholder="FL"
                  data-testid="heir-reg-address-region"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-address-postal">
                  Postal / ZIP Code (optional)
                </label>
                <input
                  id="heir-address-postal"
                  className="form-input"
                  value={regForm.address_postal_code}
                  onChange={(e) => setRegForm((p) => ({ ...p, address_postal_code: e.target.value }))}
                  placeholder="33556"
                  data-testid="heir-reg-address-postal"
                />
              </div>
              <div>
                <label className="form-label" htmlFor="heir-address-country">
                  Country (optional)
                </label>
                <input
                  id="heir-address-country"
                  className="form-input"
                  value={regForm.address_country}
                  onChange={(e) => setRegForm((p) => ({ ...p, address_country: e.target.value }))}
                  placeholder="United States"
                  data-testid="heir-reg-address-country"
                />
              </div>
            </div>
            <button
              className="btn btn-primary btn-sm"
              type="submit"
              disabled={registering}
              style={{ marginTop: 'var(--space-md)' }}
              data-testid="heir-reg-submit"
            >
              {registering ? 'Registering...' : 'Register Heir'}
            </button>
          </form>
        </div>
      )}

      {/* Heir Monitor Table */}
      <div className="archival-card">
        <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-md)' }}>
          Heir Monitor
        </h3>

        {loading ? (
          <p className="text-muted">Loading heirs...</p>
        ) : heirs.length === 0 ? (
          <p className="text-muted">
            {isSetup
              ? 'No heirs registered yet. Use the form above to add beneficiaries.'
              : 'No heirs registered for this session.'}
          </p>
        ) : (
          <div className="responsive-table-container">
            <table
              className="heir-monitor-table admin-table"
              data-testid="heir-monitor-table"
            >
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Phone</th>
                  <th>Address</th>
                  <th>Status</th>
                  <th>Invite Token</th>
                  <th>Dispatched</th>
                  <th>Expires</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {heirs.map((heir) => (
                  <tr
                    key={heir.id}
                    data-testid={`heir-row-${heir.id}`}
                  >
                    <td>
                      {heir.username || `${heir.legal_first_name || ''} ${heir.legal_last_name || ''}`.trim() || '—'}
                    </td>
                    <td>{heir.email || '—'}</td>
                    <td>{heir.phone || '—'}</td>
                    <td style={{ maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {composeAddress(heir) || heir.physical_address || '—'}
                    </td>
                    <td>{statusCheckmark(heir.user_status || heir.status)}</td>
                    <td>
                      {heir.invite_token ? (
                        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <code style={{ fontSize: '0.7rem' }}>
                            {heir.invite_token.substring(0, 8)}...
                          </code>
                          <button
                            className="btn btn-secondary"
                            style={{ padding: '0 4px', fontSize: '0.65rem', lineHeight: 1.2 }}
                            onClick={() => handleCopyToken(heir.invite_token)}
                            title="Copy token"
                            data-testid={`copy-token-${heir.id}`}
                          >
                            📋
                          </button>
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>{formatDate(heir.invite_dispatched_at)}</td>
                    <td>{formatDate(heir.invite_token_expires_at)}</td>
                    <td>
                      <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        {isSetup && (
                          <>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => handleRegenerateToken(heir.id)}
                              style={{ fontSize: '0.65rem', padding: '2px 6px' }}
                              data-testid={`regen-token-${heir.id}`}
                            >
                              🔄 Token
                            </button>
                            <button
                              className="btn btn-primary btn-sm"
                              onClick={() => handleSendInvite(heir.id)}
                              style={{ fontSize: '0.65rem', padding: '2px 6px' }}
                              data-testid={`send-invite-${heir.id}`}
                            >
                              ✉ Send
                            </button>
                            {heir.invite_token && (
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => handleCopyInvite(heir)}
                                style={{ fontSize: '0.65rem', padding: '2px 6px' }}
                                data-testid={`copy-invite-${heir.id}`}
                              >
                                Copy Invite
                              </button>
                            )}
                          </>
                        )}
                        {(heir.status === 'PROFILE_HOLD' || heir.user_status === 'PROFILE_HOLD' || heir.id_scan_uri) && (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => setSelectedIdentityHeir(heir)}
                            style={{ fontSize: '0.65rem', padding: '2px 6px' }}
                            data-testid={`inspect-id-${heir.id}`}
                          >
                            Inspect ID
                          </button>
                        )}
                        {isSetup && (
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleDeleteHeir(heir.id, heir.username || heir.email)}
                            style={{ fontSize: '0.65rem', padding: '2px 6px', color: '#DC2626' }}
                            data-testid={`delete-heir-${heir.id}`}
                          >
                            🗑
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedIdentityHeir && (
        <AdminInspectIDModal
          heir={selectedIdentityHeir}
          onClose={() => setSelectedIdentityHeir(null)}
          onVerificationComplete={handleVerificationComplete}
        />
      )}
    </div>
  );
}

const thStyle = {
  padding: 'var(--space-sm)',
  textAlign: 'left',
  fontWeight: 600,
  color: 'var(--color-text)',
  whiteSpace: 'nowrap',
};

const tdStyle = {
  padding: 'var(--space-sm)',
  verticalAlign: 'top',
  color: 'var(--color-text)',
};
