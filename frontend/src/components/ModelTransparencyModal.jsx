import React, { useState, useEffect } from 'react';

/**
 * ModelTransparencyModal — California AB 2013 AI Training Data Transparency.
 *
 * Per Compliance Spec §3.6 and UI Spec §8.6:
 * Displays a structured table of all AI models powering the system,
 * fetched from GET /api/system/models. Shown when the user clicks
 * "AI Model Details & Training Transparency" in the help drawer.
 */

export default function ModelTransparencyModal({ isOpen, onClose }) {
  const [models, setModels] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (isOpen) {
      fetchModels();
    }
  }, [isOpen]);

  async function fetchModels() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/system/models');
      if (!res.ok) {
        throw new Error('Failed to load model transparency data');
      }
      const data = await res.json();
      setModels(data.models || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div
      className="help-modal-backdrop"
      onClick={onClose}
      data-testid="transparency-backdrop"
    >
      <div
        className="help-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        data-testid="model-transparency-modal"
      >
        <div className="help-modal-header">
          <h2 style={{ fontFamily: 'var(--font-serif)', margin: 0 }}>
            AI Model Details & Training Transparency
          </h2>
          <button
            className="close-btn"
            onClick={onClose}
            aria-label="Close"
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="help-modal-body">
          <p
            style={{
              marginBottom: 'var(--space-lg)',
              color: 'var(--color-text)',
              fontSize: '0.875rem',
              lineHeight: 1.6,
            }}
          >
            In compliance with California Assembly Bill 2013 (AB 2013), the
            following table discloses the AI models, parameter counts,
            licensing, and training data provenance used by The Estate Steward.
          </p>

          {loading && (
            <p className="text-sm text-muted">Loading model information…</p>
          )}

          {error && (
            <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
              {error}
            </div>
          )}

          {!loading && !error && models.length > 0 && (
            <div className="models-table-wrapper" data-testid="models-table">
              {models.map((model, idx) => (
                <div
                  key={idx}
                  className="archival-card"
                  style={{
                    padding: 'var(--space-md)',
                    marginBottom: 'var(--space-sm)',
                  }}
                  data-testid={`model-row-${idx}`}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'baseline',
                      flexWrap: 'wrap',
                      gap: 'var(--space-xs)',
                      marginBottom: 'var(--space-xs)',
                    }}
                  >
                    <strong style={{ color: 'var(--color-primary)' }}>
                      {model.component}
                    </strong>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        color: 'var(--color-text)',
                        opacity: 0.7,
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {model.name} ({model.parameters})
                    </span>
                  </div>

                  <p
                    style={{
                      fontSize: '0.8125rem',
                      color: 'var(--color-text)',
                      opacity: 0.85,
                      margin: 0,
                      lineHeight: 1.5,
                    }}
                  >
                    {model.provenance}
                  </p>

                  <p
                    style={{
                      fontSize: '0.6875rem',
                      color: 'var(--color-text)',
                      opacity: 0.5,
                      margin: 'var(--space-xs) 0 0 0',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    License: {model.license}
                  </p>
                </div>
              ))}
            </div>
          )}

          {!loading && !error && models.length === 0 && (
            <p className="text-sm text-muted" style={{ fontStyle: 'italic' }}>
              No model transparency data available at this time.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}