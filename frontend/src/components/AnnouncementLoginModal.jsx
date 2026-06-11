import React, { useState, useEffect } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function AnnouncementLoginModal() {
  const announcement = useMediationStore((s) => s.announcement);
  const updatedAt = useMediationStore((s) => s.announcement_updated_at);
  const isAuthenticated = useMediationStore((s) => s.isAuthenticated);
  const userRole = useMediationStore((s) => s.userRole);
  
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (isAuthenticated && userRole === 'HEIR' && announcement && updatedAt) {
      const isAck = localStorage.getItem(`announcement_ack_${updatedAt}`);
      setShowModal(!isAck);
    } else {
      setShowModal(false);
    }
  }, [isAuthenticated, userRole, announcement, updatedAt]);

  if (!showModal) return null;

  const handleAcknowledge = () => {
    if (updatedAt) {
      localStorage.setItem(`announcement_ack_${updatedAt}`, 'true');
    }
    setShowModal(false);
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.4)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: 'var(--space-md)',
      }}
      data-testid="announcement-modal-overlay"
    >
      <div
        className="archival-card"
        style={{
          maxWidth: '500px',
          width: '100%',
          padding: 'var(--space-xl)',
          background: 'var(--color-card-bg)',
          textAlign: 'center',
        }}
        data-testid="announcement-modal"
      >
        <h2
          style={{
            fontFamily: 'var(--font-serif)',
            marginBottom: 'var(--space-md)',
          }}
        >
          Important Estate Notice
        </h2>
        <p
          style={{
            color: 'var(--color-text)',
            marginBottom: 'var(--space-lg)',
            textAlign: 'left',
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
          }}
        >
          {announcement}
        </p>
        <button
          className="btn btn-primary"
          onClick={handleAcknowledge}
          style={{
            margin: '0 auto',
            display: 'block',
          }}
          data-testid="announcement-ack-btn"
        >
          Acknowledge & Close
        </button>
      </div>
    </div>
  );
}
