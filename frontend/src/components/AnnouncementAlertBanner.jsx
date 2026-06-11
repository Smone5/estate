import React, { useState, useEffect } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function AnnouncementAlertBanner() {
  const announcement = useMediationStore((s) => s.announcement);
  const updatedAt = useMediationStore((s) => s.announcement_updated_at);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (updatedAt) {
      const isDismissed = sessionStorage.getItem(`announcement_dismissed_${updatedAt}`);
      setDismissed(!!isDismissed);
    } else {
      setDismissed(false);
    }
  }, [updatedAt]);

  if (!announcement || dismissed) return null;

  const handleDismiss = () => {
    if (updatedAt) {
      sessionStorage.setItem(`announcement_dismissed_${updatedAt}`, 'true');
    }
    setDismissed(true);
  };

  return (
    <div
      className="announcement-banner"
      style={{
        background: 'var(--color-alert-light)',
        border: '1px solid var(--color-alert)',
        borderRadius: 'var(--radius-sm)',
        padding: 'var(--space-sm) var(--space-md)',
        margin: 'var(--space-md) var(--space-md) 0 var(--space-md)',
        color: 'var(--color-text)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 'var(--space-md)',
      }}
      data-testid="announcement-banner"
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', flex: 1 }}>
        <span style={{ color: 'var(--color-alert)', fontSize: '1.2rem' }}>📢</span>
        <span>{announcement}</span>
      </div>
      <button
        onClick={handleDismiss}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--color-text-muted)',
          cursor: 'pointer',
          textDecoration: 'underline',
          fontSize: '0.85rem',
          padding: 0,
        }}
        data-testid="announcement-dismiss-btn"
      >
        Dismiss
      </button>
    </div>
  );
}
