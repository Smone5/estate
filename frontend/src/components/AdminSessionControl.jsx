import React, { useState, useEffect, useCallback, useMemo } from 'react';
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

const HEIR_PAGE_SIZE = 25;

const STATUS_PRIORITY = {
  PROFILE_HOLD: 0,
  PENDING: 1,
  ACTIVE: 2,
  SUBMITTED: 3,
  ABSTAINED: 4,
  EXPIRED_NON_PARTICIPATING: 5,
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
  section = 'all',
}) {
  const sessionStatus = useMediationStore((s) => s.sessionStatus);

  const [internalHeirs, setInternalHeirs] = useState([]);
  const [loading, setLoading] = useState(propHeirs === undefined);
  const [actionError, setActionError] = useState(null);
  const [actionSuccess, setActionSuccess] = useState(null);
  const [selectedIdentityHeir, setSelectedIdentityHeir] = useState(null);
  const [heirOverrides, setHeirOverrides] = useState({});
  const [heirSearch, setHeirSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sortMode, setSortMode] = useState('priority');
  const [cardDensity, setCardDensity] = useState('compact');
  const [visibleCount, setVisibleCount] = useState(HEIR_PAGE_SIZE);

  const baseHeirs = propHeirs !== undefined ? propHeirs : internalHeirs;
  const heirs = baseHeirs.map((heir) => (
    heirOverrides[heir.id] ? { ...heir, ...heirOverrides[heir.id] } : heir
  ));
  const identityReviewHeirs = heirs.filter(
    (heir) => (heir.status === 'PROFILE_HOLD' || heir.user_status === 'PROFILE_HOLD') && heir.id_scan_uri,
  );
  const rosterStats = useMemo(() => {
    const stats = {
      all: heirs.length,
      needsAction: 0,
      pending: 0,
      active: 0,
      submitted: 0,
    };
    heirs.forEach((heir) => {
      const status = getHeirStatusValue(heir);
      if (needsHeirAction(heir)) stats.needsAction += 1;
      if (status === 'PENDING') stats.pending += 1;
      if (status === 'ACTIVE') stats.active += 1;
      if (status === 'SUBMITTED') stats.submitted += 1;
    });
    return stats;
  }, [heirs]);
  const filteredHeirs = useMemo(() => {
    const query = heirSearch.trim().toLowerCase();

    return heirs
      .filter((heir) => {
        const status = getHeirStatusValue(heir);
        if (statusFilter === 'needs_action' && !needsHeirAction(heir)) return false;
        if (statusFilter !== 'all' && statusFilter !== 'needs_action' && status !== statusFilter) return false;
        if (!query) return true;

        return [
          getHeirDisplayName(heir),
          heir.email,
          heir.phone,
          composeAddress(heir),
          heir.physical_address,
          heir.invite_token,
          status,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(query);
      })
      .sort((a, b) => compareHeirs(a, b, sortMode));
  }, [heirs, heirSearch, statusFilter, sortMode]);
  const visibleHeirs = filteredHeirs.slice(0, visibleCount);
  const hasMoreHeirs = filteredHeirs.length > visibleHeirs.length;

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

  useEffect(() => {
    setVisibleCount(HEIR_PAGE_SIZE);
  }, [heirSearch, statusFilter, sortMode, heirs.length]);

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

  function getHeirStatusValue(heir) {
    return heir.user_status || heir.status || 'PENDING';
  }

  function getHeirDisplayName(heir) {
    return heir.username || `${heir.legal_first_name || ''} ${heir.legal_last_name || ''}`.trim() || 'Unnamed heir';
  }

  function needsHeirAction(heir) {
    const status = getHeirStatusValue(heir);
    return (
      status === 'PENDING' ||
      status === 'PROFILE_HOLD' ||
      status === 'EXPIRED_NON_PARTICIPATING' ||
      Boolean(heir.id_scan_uri) ||
      !heir.invite_dispatched_at
    );
  }

  function compareHeirs(a, b, mode) {
    const statusA = getHeirStatusValue(a);
    const statusB = getHeirStatusValue(b);
    const nameA = getHeirDisplayName(a).toLowerCase();
    const nameB = getHeirDisplayName(b).toLowerCase();

    if (mode === 'name') return nameA.localeCompare(nameB);
    if (mode === 'status') {
      return (STATUS_PRIORITY[statusA] ?? 99) - (STATUS_PRIORITY[statusB] ?? 99) || nameA.localeCompare(nameB);
    }
    if (mode === 'expires') {
      const timeA = a.invite_token_expires_at ? new Date(a.invite_token_expires_at).getTime() : Number.MAX_SAFE_INTEGER;
      const timeB = b.invite_token_expires_at ? new Date(b.invite_token_expires_at).getTime() : Number.MAX_SAFE_INTEGER;
      return timeA - timeB || nameA.localeCompare(nameB);
    }
    if (mode === 'recent_invite') {
      const timeA = a.invite_dispatched_at ? new Date(a.invite_dispatched_at).getTime() : 0;
      const timeB = b.invite_dispatched_at ? new Date(b.invite_dispatched_at).getTime() : 0;
      return timeB - timeA || nameA.localeCompare(nameB);
    }

    const actionA = needsHeirAction(a) ? 0 : 1;
    const actionB = needsHeirAction(b) ? 0 : 1;
    return actionA - actionB || (STATUS_PRIORITY[statusA] ?? 99) - (STATUS_PRIORITY[statusB] ?? 99) || nameA.localeCompare(nameB);
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
  function heirStatus(status) {
    if (status === 'SUBMITTED') {
      return {
        icon: '✅',
        label: 'Submitted',
        className: 'heir-status-pill heir-status-pill--submitted',
        guidance: 'Valuations locked',
      };
    }
    if (status === 'ABSTAINED') {
      return {
        icon: '○',
        label: 'Abstained',
        className: 'heir-status-pill heir-status-pill--quiet',
        guidance: 'Waiver recorded',
      };
    }
    if (status === 'EXPIRED_NON_PARTICIPATING') {
      return {
        icon: '□',
        label: 'Expired',
        className: 'heir-status-pill heir-status-pill--quiet',
        guidance: 'Notice window closed',
      };
    }
    if (status === 'PROFILE_HOLD') {
      return {
        icon: '!',
        label: 'ID Hold',
        className: 'heir-status-pill heir-status-pill--review',
        guidance: 'Review identity',
      };
    }
    if (status === 'ACTIVE') {
      return {
        icon: '•',
        label: 'Active',
        className: 'heir-status-pill heir-status-pill--active',
        guidance: 'Can participate',
      };
    }
    return {
      icon: '⏳',
      label: 'Pending',
      className: 'heir-status-pill heir-status-pill--pending',
      guidance: 'Invite not completed',
    };
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
  const showRegisterSection = isSetup && (section === 'all' || section === 'register');
  const showMonitorSection = section === 'all' || section === 'monitor';

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
      {showRegisterSection && (
        <div id="register-heir-section" className="archival-card" style={{ marginBottom: showMonitorSection ? 'var(--space-lg)' : 0 }}>
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
      {showMonitorSection && (
      <div className="archival-card">
        <div className="heir-monitor-heading">
          <div>
            <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-xs)' }}>
              Heir Monitor
            </h3>
            {!loading && heirs.length > 0 && (
              <p className="text-muted text-sm">
                Showing {visibleHeirs.length} of {filteredHeirs.length} matching heirs.
              </p>
            )}
          </div>
          {!loading && heirs.length > 0 && (
            <div className="heir-density-toggle" aria-label="Heir card density">
              <button
                type="button"
                className={cardDensity === 'compact' ? 'active' : ''}
                onClick={() => setCardDensity('compact')}
              >
                Roster
              </button>
              <button
                type="button"
                className={cardDensity === 'detail' ? 'active' : ''}
                onClick={() => setCardDensity('detail')}
              >
                Full Card
              </button>
            </div>
          )}
        </div>

        {loading ? (
          <p className="text-muted">Loading heirs...</p>
        ) : heirs.length === 0 ? (
          <p className="text-muted">
            {isSetup
              ? 'No heirs registered yet. Use the form above to add beneficiaries.'
              : 'No heirs registered for this session.'}
          </p>
        ) : (
          <>
            <div className="heir-monitor-toolbar">
              <div className="heir-stat-strip" aria-label="Heir status summary">
                <button type="button" className={statusFilter === 'all' ? 'active' : ''} onClick={() => setStatusFilter('all')}>
                  <span>{rosterStats.all}</span>
                  <small>All</small>
                </button>
                <button type="button" className={statusFilter === 'needs_action' ? 'active' : ''} onClick={() => setStatusFilter('needs_action')}>
                  <span>{rosterStats.needsAction}</span>
                  <small>Needs Action</small>
                </button>
                <button type="button" className={statusFilter === 'PENDING' ? 'active' : ''} onClick={() => setStatusFilter('PENDING')}>
                  <span>{rosterStats.pending}</span>
                  <small>Pending</small>
                </button>
                <button type="button" className={statusFilter === 'ACTIVE' ? 'active' : ''} onClick={() => setStatusFilter('ACTIVE')}>
                  <span>{rosterStats.active}</span>
                  <small>Active</small>
                </button>
                <button type="button" className={statusFilter === 'SUBMITTED' ? 'active' : ''} onClick={() => setStatusFilter('SUBMITTED')}>
                  <span>{rosterStats.submitted}</span>
                  <small>Submitted</small>
                </button>
              </div>

              <div className="heir-filter-grid">
                <div>
                  <label className="form-label" htmlFor="heir-monitor-search">Search heirs</label>
                  <input
                    id="heir-monitor-search"
                    className="form-input"
                    value={heirSearch}
                    onChange={(e) => setHeirSearch(e.target.value)}
                    placeholder="Name, email, phone, token..."
                    data-testid="heir-monitor-search"
                  />
                </div>
                <div>
                  <label className="form-label" htmlFor="heir-monitor-status">Filter</label>
                  <select
                    id="heir-monitor-status"
                    className="form-input"
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    data-testid="heir-monitor-status-filter"
                  >
                    <option value="all">All statuses</option>
                    <option value="needs_action">Needs action</option>
                    <option value="PENDING">Pending</option>
                    <option value="PROFILE_HOLD">ID hold</option>
                    <option value="ACTIVE">Active</option>
                    <option value="SUBMITTED">Submitted</option>
                    <option value="ABSTAINED">Abstained</option>
                    <option value="EXPIRED_NON_PARTICIPATING">Expired</option>
                  </select>
                </div>
                <div>
                  <label className="form-label" htmlFor="heir-monitor-sort">Sort</label>
                  <select
                    id="heir-monitor-sort"
                    className="form-input"
                    value={sortMode}
                    onChange={(e) => setSortMode(e.target.value)}
                    data-testid="heir-monitor-sort"
                  >
                    <option value="priority">Priority first</option>
                    <option value="name">Name A-Z</option>
                    <option value="status">Status</option>
                    <option value="expires">Invite expiring soon</option>
                    <option value="recent_invite">Recently invited</option>
                  </select>
                </div>
              </div>
            </div>

            {filteredHeirs.length === 0 ? (
              <div className="heir-monitor-empty">
                <strong>No matching heirs</strong>
                <span>Adjust the search or filters to widen the roster.</span>
              </div>
            ) : (
              <div className={`heir-card-grid heir-card-grid--${cardDensity}`} data-testid="heir-monitor-table">
                {visibleHeirs.map((heir) => {
              const status = heirStatus(heir.user_status || heir.status);
              const displayName = getHeirDisplayName(heir);
              const address = composeAddress(heir) || heir.physical_address || 'No address on file';

              return (
                <article key={heir.id} className={`heir-card heir-card--${cardDensity}`} data-testid={`heir-row-${heir.id}`}>
                  <div className="heir-card-header">
                    <div className="heir-card-identity">
                      <h4 className="heir-card-name">{displayName}</h4>
                      <p className="heir-card-guidance">{status.guidance}</p>
                    </div>
                    <span className={status.className}>
                      {status.label === 'Pending' ? (
                        <span>{status.icon} {status.label}</span>
                      ) : (
                        <>
                          <span className="heir-status-icon" aria-hidden="true">{status.icon}</span>{' '}
                          <span>{status.label}</span>
                        </>
                      )}
                    </span>
                  </div>

                  <div className="heir-compact-meta" aria-label={`${displayName} roster summary`}>
                    <span>{heir.email || 'No email on file'}</span>
                    <span>Expires {formatDate(heir.invite_token_expires_at)}</span>
                  </div>

                  <div className="heir-contact-stack" aria-label={`${displayName} contact details`}>
                    <div className="heir-contact-line">
                      <span className="heir-card-label">Email</span>
                      <span className="heir-card-value">{heir.email || 'No email on file'}</span>
                    </div>
                    <div className="heir-contact-line">
                      <span className="heir-card-label">Phone</span>
                      <span className="heir-card-value">{heir.phone || 'No phone on file'}</span>
                    </div>
                    <div className="heir-contact-line heir-contact-line--address">
                      <span className="heir-card-label">Address</span>
                      <span className="heir-card-value">{address}</span>
                    </div>
                  </div>

                  <div className="heir-invite-panel">
                    <div className="heir-token-row">
                      <span className="heir-card-label">Invite Token</span>
                      {heir.invite_token ? (
                        <div className="heir-token-value">
                          <code>{heir.invite_token.substring(0, 8)}...</code>
                          <button
                            className="btn btn-secondary btn-sm heir-token-copy"
                            onClick={() => handleCopyToken(heir.invite_token)}
                            title="Copy invite token"
                            data-testid={`copy-token-${heir.id}`}
                          >
                            Copy
                          </button>
                        </div>
                      ) : (
                        <span className="heir-card-value">No token</span>
                      )}
                    </div>

                    <div className="heir-date-grid">
                      <div>
                        <span className="heir-card-label">Dispatched</span>
                        <span className="heir-card-value">{formatDate(heir.invite_dispatched_at)}</span>
                      </div>
                      <div>
                        <span className="heir-card-label">Expires</span>
                        <span className="heir-card-value">{formatDate(heir.invite_token_expires_at)}</span>
                      </div>
                    </div>
                  </div>

                  <div className="heir-card-actions">
                    {isSetup && (
                      <>
                        <button
                          className="btn btn-secondary btn-sm heir-secondary-action"
                          onClick={() => handleRegenerateToken(heir.id)}
                          data-testid={`regen-token-${heir.id}`}
                        >
                          Renew Token
                        </button>
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => handleSendInvite(heir.id)}
                          data-testid={`send-invite-${heir.id}`}
                        >
                          Send Invite
                        </button>
                        {heir.invite_token && (
                          <button
                            className="btn btn-secondary btn-sm heir-secondary-action"
                            onClick={() => handleCopyInvite(heir)}
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
                        data-testid={`inspect-id-${heir.id}`}
                      >
                        Inspect ID
                      </button>
                    )}
                    {isSetup && (
                      <button
                        className="btn btn-danger btn-sm heir-delete-btn heir-secondary-action"
                        onClick={() => handleDeleteHeir(heir.id, heir.username || heir.email)}
                        data-testid={`delete-heir-${heir.id}`}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </article>
              );
                })}
              </div>
            )}

            {hasMoreHeirs && (
              <div className="heir-load-more">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setVisibleCount((count) => count + HEIR_PAGE_SIZE)}
                >
                  Show {Math.min(HEIR_PAGE_SIZE, filteredHeirs.length - visibleHeirs.length)} More
                </button>
              </div>
            )}
          </>
        )}
      </div>
      )}

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
