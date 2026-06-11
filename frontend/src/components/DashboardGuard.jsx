import { useMediationStore } from '../store/useMediationStore';

/**
 * Renders the appropriate status banner and optionally disables controls
 * based on session and user state per Frontend Spec §5.4.
 *
 * Props:
 *   variant: 'heir' | 'admin' | 'placeholder'
 *   children: the dashboard content to wrap
 */
export default function DashboardGuard({ variant = 'heir', children }) {
  const sessionStatus = useMediationStore((s) => s.sessionStatus);
  const userStatus = useMediationStore((s) => s.userStatus);
  const isPaused = useMediationStore((s) => s.isPaused);
  const isDeadlocked = useMediationStore((s) => s.isDeadlocked);
  const is_hitl_suspended = useMediationStore((s) => s.is_hitl_suspended);
  const isSubmitted = useMediationStore((s) => s.isSubmitted);
  const isAuthenticated = useMediationStore((s) => s.isAuthenticated);

  // Redirect is handled by the router, but double-check here
  if (!isAuthenticated && variant !== 'placeholder') {
    return null;
  }

  // ── Abstention / Expiration Gate ──────────────────────────────────────
  if (userStatus === 'ABSTAINED' || userStatus === 'EXPIRED_NON_PARTICIPATING') {
    return (
      <div className="app-main flex items-center justify-center" style={{ flex: 1, padding: 'var(--space-lg)' }}>
        <div className="archival-card text-center" style={{ maxWidth: 520, width: '100%' }}>
          <h2 style={{ marginBottom: 'var(--space-md)' }}>Non-Participation Status</h2>
          <p className="text-muted" style={{ marginBottom: 'var(--space-lg)' }}>
            {userStatus === 'ABSTAINED'
              ? 'You have formally abstained from the asset allocation process. Your participation in this mediation session is complete.'
              : 'Your invitation has expired and you have been marked as non-participating in this mediation session.'}
          </p>
          <p className="text-sm text-muted">
            The Executor has been notified. You may download your records from the Executor upon request.
          </p>
        </div>
      </div>
    );
  }

  // ── Finalized Keepsake Layout ─────────────────────────────────────────
  if (sessionStatus === 'FINALIZED') {
    return (
      <div className="app-main" style={{ flex: 1, padding: 'var(--space-lg)', overflowY: 'auto' }}>
        <div className="archival-card" style={{ maxWidth: 720, margin: '0 auto' }}>
          <h2 style={{ marginBottom: 'var(--space-md)' }}>Keepsake Memory Book</h2>
          <p className="text-muted" style={{ marginBottom: 'var(--space-md)' }}>
            The mediation session has been finalized. Your final asset allocations are displayed below.
            You may download your keepsake PDF from this page.
          </p>
          <div className="banner banner-info" style={{ marginBottom: 'var(--space-md)' }}>
            Final allocations have been recorded in the probate audit ledger.
          </div>
          {children}
        </div>
      </div>
    );
  }

  // ── Determine which banner to show and whether to disable controls ────
  let banner = null;
  let disableControls = false;
  let disableChat = false;
  let keepDraftEnabled = false;

  if (sessionStatus === 'SETUP') {
    banner = {
      type: 'info',
      text: 'Welcome! The Executor is currently setting up the estate catalog. Sliders and mediation chat will unlock once the session is launched.',
    };
    disableControls = true;
    disableChat = true;
  } else if (userStatus === 'PROFILE_HOLD') {
    banner = {
      type: 'warning',
      text: 'Profile Hold. Your identity details are unverified or require correction. Sliders and chat are locked until approved.',
    };
    disableControls = true;
    disableChat = true;
  } else if (isPaused) {
    banner = {
      type: 'amber',
      text: 'Session Paused. The mediation space has been temporarily paused by the Executor.',
    };
    disableControls = true;
    disableChat = true;
  } else if (is_hitl_suspended) {
    banner = {
      type: 'error',
      text: 'Points submission suspended. Your allocations require review and correction by the Executor.',
    };
    disableControls = true;
    disableChat = true;
    keepDraftEnabled = true;
  } else if (isSubmitted) {
    banner = {
      type: 'success',
      text: 'Valuations Submitted. Your selections are now locked. Waiting for other family members to submit.',
    };
    disableControls = true;
    disableChat = false;
  } else if (sessionStatus === 'LOCKED') {
    if (isDeadlocked) {
      banner = {
        type: 'amber',
        text: 'Conflict Review. The session is temporarily under review by the Executor to resolve conflicting allocations.',
      };
    }
    disableControls = true;
    disableChat = true;
  }

  return (
    <div className="app-main" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      {/* SB 1001 AI Mediator bot disclosure — permanent, always visible */}
      <div className="ai-mediator-banner banner banner-info" style={{ borderRadius: 0, borderTop: '1px solid var(--color-border)', borderBottom: '1px solid var(--color-border)' }}>
        <strong>AI Mediator Agent</strong>
        <span className="text-sm text-muted" style={{ marginLeft: 'var(--space-sm)' }}>
          Chatting with AI Mediator
        </span>
      </div>

      {/* Status banner (if any) */}
      {banner && (
        <div
          className={`banner banner-${banner.type}`}
          style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none' }}
        >
          {banner.text}
          {keepDraftEnabled && (
            <span className="text-sm" style={{ display: 'block', marginTop: 'var(--space-xs)' }}>
              Draft saving remains enabled while points are under review.
            </span>
          )}
        </div>
      )}

      {/* Wrap children with disabled state context via data attributes */}
      <div
        data-dashboard-controls-disabled={disableControls ? 'true' : 'false'}
        data-dashboard-chat-disabled={disableChat ? 'true' : 'false'}
        data-dashboard-draft-enabled={keepDraftEnabled ? 'true' : 'false'}
        style={{ flex: 1, display: 'flex', flexDirection: 'column' }}
      >
        {children}
      </div>
    </div>
  );
}