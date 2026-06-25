import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import { customConfirm } from '../store/useDialogStore';

export default function AdminSetupChecklist({
  sessionId,
  heirs = [],
  assets = [],
  onLaunch,
  onNavigateToTab,
}) {
  const store = useMediationStore();
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState(null);

  const publishedCount = assets.filter((a) => a.status === 'LIVE' || a.status === 'PRE_ALLOCATED').length;
  const stagedCount = assets.filter((a) => a.status === 'STAGED' || !a.status).length;
  const heirsCount = heirs.length;

  // Compute checklist completeness
  const step1Completed = heirsCount > 0;
  const step2Completed = publishedCount > 0 && stagedCount === 0;
  const isReadyToLaunch = publishedCount > 0; // Backend requirement: at least one published asset

  let completedSteps = 0;
  if (step1Completed) completedSteps++;
  if (step2Completed) completedSteps++;
  const progressPercent = Math.round((completedSteps / 2) * 100);

  const navigateToSection = (tab, id) => {
    if (onNavigateToTab) {
      onNavigateToTab(tab);
    }

    window.setTimeout(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 0);
  };

  const handleLaunch = async () => {
    if (!await customConfirm('Launch the session? This will lock the asset catalog and open mediation to all heirs. This action cannot be undone.')) {
      return;
    }

    setLaunching(true);
    setError(null);

    try {
      const res = await fetch(`/api/sessions/${sessionId}/launch`, {
        method: 'POST',
        credentials: 'same-origin',
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Launch failed: ${res.status}`);
      }

      await store.loadSessionDetails();
      if (onLaunch) {
        onLaunch();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLaunching(false);
    }
  };

  return (
    <div className="archival-card" data-testid="admin-setup-checklist" style={{ borderLeft: '4px solid var(--color-primary)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--space-md)', marginBottom: 'var(--space-md)' }}>
        <div>
          <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: '4px' }}>
            Getting Started: Session Setup Guide
          </h3>
          <p className="text-muted text-sm" style={{ margin: 0 }}>
            Complete the steps below to prepare and launch this mediation session.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
          <span className="text-sm font-semibold tabular-value" style={{ color: 'var(--color-primary)' }}>
            {progressPercent}% Complete
          </span>
        </div>
      </div>

      {/* Progress Bar */}
      <div style={{ width: '100%', height: '6px', background: 'var(--color-border)', borderRadius: '3px', overflow: 'hidden', marginBottom: 'var(--space-lg)' }}>
        <div
          style={{
            width: `${progressPercent}%`,
            height: '100%',
            background: 'var(--color-primary)',
            transition: 'width 0.4s ease-out',
          }}
        />
      </div>

      {error && (
        <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
          {error}
        </div>
      )}

      {/* Steps Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 'var(--space-md)',
        }}
      >
        {/* Step 1: Heirs */}
        <div
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-md)',
            background: step1Completed ? 'var(--color-primary-light)' : 'transparent',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: 'var(--space-sm)',
          }}
        >
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-xs)' }}>
              <strong style={{ fontSize: '0.9rem' }}>1. Register Heirs</strong>
              <span
                className="badge"
                style={{
                  fontSize: '0.65rem',
                  padding: '1px 6px',
                  background: step1Completed ? '#DCFCE7' : '#FEF3C7',
                  color: step1Completed ? '#166534' : '#92400E',
                  border: 'none',
                }}
              >
                {step1Completed ? '✅ Registered' : '⏳ Action Required'}
              </span>
            </div>
            <p className="text-muted text-xs" style={{ margin: 0 }}>
              Add beneficiaries who will participate. They must be registered before the session launches to receive invite links.
            </p>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'var(--space-xs)' }}>
            <span className="text-xs font-semibold">
              Registered: <strong className="tabular-value">{heirsCount}</strong>
            </span>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => navigateToSection('heirs', 'register-heir-section')}
              style={{ fontSize: '0.75rem', padding: '4px 8px' }}
              data-testid="checklist-goto-heirs-btn"
            >
              {heirsCount > 0 ? 'Manage Heirs' : 'Add Heirs'}
            </button>
          </div>
        </div>

        {/* Step 2: Keepsakes */}
        <div
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-md)',
            background: step2Completed ? 'var(--color-primary-light)' : 'transparent',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: 'var(--space-sm)',
          }}
        >
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-xs)' }}>
              <strong style={{ fontSize: '0.9rem' }}>2. Catalog Keepsakes</strong>
              <span
                className="badge"
                style={{
                  fontSize: '0.65rem',
                  padding: '1px 6px',
                  background: step2Completed ? '#DCFCE7' : (stagedCount > 0 ? '#FEF3C7' : '#F3F4F6'),
                  color: step2Completed ? '#166534' : (stagedCount > 0 ? '#92400E' : '#4B5563'),
                  border: 'none',
                }}
              >
                {step2Completed ? '✅ Cataloged' : (stagedCount > 0 ? '⚠️ Publish Drafts' : '⏳ Empty')}
              </span>
            </div>
            <p className="text-muted text-xs" style={{ margin: 0 }}>
              Upload item photos. Background OCR extracts details. Edit and publish items so heirs can allocate points.
            </p>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'var(--space-xs)' }}>
            <span className="text-xs font-semibold">
              Live: <strong className="tabular-value" style={{ color: '#166534' }}>{publishedCount}</strong> | Draft: <strong className="tabular-value" style={{ color: stagedCount > 0 ? '#92400E' : 'inherit' }}>{stagedCount}</strong>
            </span>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => navigateToSection('catalog', 'upload-asset-section')}
              style={{ fontSize: '0.75rem', padding: '4px 8px' }}
              data-testid="checklist-goto-upload-btn"
            >
              Stage Asset
            </button>
          </div>
        </div>

        {/* Step 3: Launch */}
        <div
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-md)',
            background: isReadyToLaunch ? 'var(--color-primary-light)' : '#F9FAFB',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: 'var(--space-sm)',
            opacity: isReadyToLaunch ? 1 : 0.8,
          }}
        >
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-xs)' }}>
              <strong style={{ fontSize: '0.9rem' }}>3. Launch Session</strong>
              <span
                className="badge"
                style={{
                  fontSize: '0.65rem',
                  padding: '1px 6px',
                  background: isReadyToLaunch ? '#DBEAFE' : '#E5E7EB',
                  color: isReadyToLaunch ? '#1E40AF' : '#6B7280',
                  border: 'none',
                }}
              >
                {isReadyToLaunch ? '🔓 Ready' : '🔒 Locked'}
              </span>
            </div>
            <p className="text-muted text-xs" style={{ margin: 0 }}>
              Once launched, the keepsake catalog is locked, and heirs can begin point allocation and chat.
            </p>
          </div>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleLaunch}
            disabled={!isReadyToLaunch || launching}
            style={{
              width: '100%',
              fontSize: '0.8rem',
              padding: '6px 12px',
              backgroundColor: isReadyToLaunch ? 'var(--color-primary)' : 'var(--color-text-muted)',
              borderColor: isReadyToLaunch ? 'var(--color-primary)' : 'var(--color-text-muted)',
            }}
            data-testid="checklist-launch-btn"
          >
            {launching ? 'Launching...' : '🚀 Launch Mediation'}
          </button>
        </div>
      </div>
    </div>
  );
}
