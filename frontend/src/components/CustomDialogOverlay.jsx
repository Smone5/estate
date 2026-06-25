import React, { useEffect, useState, useRef } from 'react';
import { useDialogStore } from '../store/useDialogStore';

export default function CustomDialogOverlay() {
  const dialog = useDialogStore((s) => s.dialog);
  const submit = useDialogStore((s) => s.submit);
  const cancel = useDialogStore((s) => s.cancel);

  const [promptValue, setPromptValue] = useState('');
  const inputRef = useRef(null);
  const okBtnRef = useRef(null);
  const cancelBtnRef = useRef(null);

  // Initialize/Reset prompt input value when dialog changes
  useEffect(() => {
    if (dialog) {
      setPromptValue(dialog.defaultValue || '');
      // Focus appropriate element
      setTimeout(() => {
        if (dialog.type === 'prompt') {
          inputRef.current?.focus();
          inputRef.current?.select();
        } else {
          okBtnRef.current?.focus();
        }
      }, 50);
    }
  }, [dialog]);

  // Keyboard navigation / focus trapping / Escape dismiss
  useEffect(() => {
    if (!dialog) return;

    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        cancel();
      }
      if (e.key === 'Tab') {
        // Simple focus trap
        const focusables = [];
        if (dialog.type === 'prompt' && inputRef.current) focusables.push(inputRef.current);
        if (cancelBtnRef.current) focusables.push(cancelBtnRef.current);
        if (okBtnRef.current) focusables.push(okBtnRef.current);

        if (focusables.length > 0) {
          const first = focusables[0];
          const last = focusables[focusables.length - 1];

          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [dialog, cancel]);

  if (!dialog) return null;

  function handleSubmit(e) {
    e.preventDefault();
    if (dialog.type === 'prompt') {
      submit(promptValue);
    } else {
      submit(true);
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(30, 41, 59, 0.55)',
        backdropFilter: 'blur(2px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 99999,
        padding: 'var(--space-md)',
      }}
      onClick={cancel}
      data-testid="custom-dialog-overlay"
    >
      <div
        className="archival-card"
        style={{
          width: '100%',
          maxWidth: '480px',
          backgroundColor: 'var(--color-card-bg)',
          borderRadius: 'var(--radius-md)',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.15), 0 10px 10px -5px rgba(0, 0, 0, 0.04), var(--shadow-card)',
          padding: 'var(--space-lg)',
          animation: 'cmFadeIn 0.15s ease-out',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-sm)' }}>
          {dialog.type === 'prompt' ? 'Action Required' : 'Confirm Action'}
        </h3>
        
        <p className="text-sm" style={{ marginBottom: 'var(--space-md)', color: 'var(--color-text)', lineHeight: 1.6 }}>
          {dialog.message}
        </p>

        <form onSubmit={handleSubmit}>
          {dialog.type === 'prompt' && (
            <div style={{ marginBottom: 'var(--space-lg)' }}>
              <input
                ref={inputRef}
                type="text"
                className="form-input"
                value={promptValue}
                onChange={(e) => setPromptValue(e.target.value)}
                style={{ width: '100%' }}
                required
                data-testid="custom-dialog-prompt-input"
              />
            </div>
          )}

          <div style={{ display: 'flex', gap: 'var(--space-sm)', justifyContent: 'flex-end' }}>
            <button
              ref={cancelBtnRef}
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={cancel}
              data-testid="custom-dialog-cancel-btn"
            >
              Cancel
            </button>
            <button
              ref={okBtnRef}
              type="submit"
              className="btn btn-primary btn-sm"
              data-testid="custom-dialog-submit-btn"
            >
              Confirm
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
