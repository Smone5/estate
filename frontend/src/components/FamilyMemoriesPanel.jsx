import React, { useState } from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function FamilyMemoriesPanel({ assetId }) {
  const valuations = useMediationStore((s) => s.valuations);
  const isPaused = useMediationStore((s) => s.isPaused);
  const isSubmitted = useMediationStore((s) => s.isSubmitted);
  const sessionStatus = useMediationStore((s) => s.sessionStatus);
  const updateValuationText = useMediationStore((s) => s.updateValuationText);

  const [expanded, setExpanded] = useState(false);
  const [localReasoning, setLocalReasoning] = useState('');
  const [localShare, setLocalShare] = useState(false);

  const isEditing = !isPaused && !isSubmitted && sessionStatus === 'ACTIVE';
  const currentVal = valuations?.[assetId] || { points: 0, reasoning: '', is_reasoning_shared: false };

  // Get shared memories from other heirs (simulated — render static stories for now,
  // the store holds valuations keyed by assetId; shared stories are those where is_reasoning_shared === true)
  // Display the current heir's own story if shared
  const hasSharedStory = currentVal.is_reasoning_shared && currentVal.reasoning;

  function toggleExpanded() {
    setExpanded((prev) => !prev);
    if (!expanded && isEditing) {
      setLocalReasoning(currentVal.reasoning || '');
      setLocalShare(currentVal.is_reasoning_shared || false);
    }
  }

  function handleSaveMemory() {
    if (isEditing && assetId) {
      updateValuationText(assetId, localReasoning, localShare);
    }
  }

  return (
    <div className="archival-card" style={{ marginTop: 'var(--space-md)' }} data-testid="family-memories-panel">
      <button
        onClick={toggleExpanded}
        className="btn btn-secondary btn-sm"
        style={{ width: '100%', textAlign: 'left' }}
        data-testid="memories-toggle-btn"
      >
        {expanded ? '▼' : '▶'} Family Memories & Stories
      </button>

      {expanded && (
        <div style={{ marginTop: 'var(--space-md)' }} data-testid="memories-content">
          {/* Shared stories from other heirs */}
          {!hasSharedStory && !isEditing && (
            <p className="text-muted text-sm" data-testid="memories-empty">
              No family memories have been shared for this item yet.
            </p>
          )}

          {hasSharedStory && (
            <div
              data-testid="shared-memory-block"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-primary-light)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-md)',
                marginBottom: 'var(--space-md)',
              }}
            >
              <p className="text-sm" style={{ fontWeight: 600, marginBottom: '4px' }}>
                Shared Memory
              </p>
              <p className="text-sm" style={{ fontStyle: 'italic', lineHeight: 1.6 }}>
                {currentVal.reasoning}
              </p>
            </div>
          )}

          {/* Editing panel (only when active and not paused/submitted) */}
          {isEditing && (
            <div
              data-testid="memories-edit-panel"
              style={{
                borderTop: '1px solid var(--color-border)',
                paddingTop: 'var(--space-md)',
              }}
            >
              <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-sm)' }}>
                Share a story or memory about why this item matters to you. Shared stories are
                visible to other family members but no replies or reactions are possible.
              </p>

              <textarea
                className="form-input"
                value={localReasoning}
                onChange={(e) => setLocalReasoning(e.target.value)}
                rows={3}
                placeholder="Write your memory here..."
                data-testid="memory-textarea"
              />

              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--space-sm)',
                  marginTop: 'var(--space-sm)',
                  marginBottom: 'var(--space-md)',
                }}
              >
                <input
                  type="checkbox"
                  id={`share-memory-${assetId || 'generic'}`}
                  checked={localShare}
                  onChange={(e) => setLocalShare(e.target.checked)}
                  data-testid="share-memory-checkbox"
                />
                <label
                  htmlFor={`share-memory-${assetId || 'generic'}`}
                  className="text-sm"
                  style={{ color: 'var(--color-text)' }}
                >
                  Share this memory with my family
                </label>
              </div>

              <button
                className="btn btn-primary btn-sm"
                onClick={handleSaveMemory}
                data-testid="save-memory-btn"
              >
                Save Memory
              </button>
            </div>
          )}

          {/* Locked message when paused or submitted */}
          {!isEditing && (isPaused || isSubmitted) && (
            <p className="text-muted text-sm" data-testid="memories-locked-msg">
              {isPaused
                ? 'Memories editing is locked while the session is paused.'
                : 'Memories are locked after submission.'}
            </p>
          )}
        </div>
      )}
    </div>
  );
}