import React from 'react';
import { useMediationStore } from '../store/useMediationStore';

export default function AutoBalanceButton() {
  const unallocatedPoints = useMediationStore((s) => s.unallocatedPoints);
  const isSubmitted = useMediationStore((s) => s.isSubmitted);
  const is_hitl_suspended = useMediationStore((s) => s.is_hitl_suspended);
  const valuations = useMediationStore((s) => s.valuations);
  const autoBalancePoints = useMediationStore((s) => s.autoBalancePoints);

  const totalAllocated = 1000 - unallocatedPoints;
  const isZeroAllocation = totalAllocated === 0;
  const disabled = isSubmitted || isZeroAllocation;
  // Still enabled during HITL suspension (spec says keep draft saving enabled)

  function handleBalance() {
    if (!disabled) {
      autoBalancePoints();
    }
  }

  return (
    <div data-testid="auto-balance-btn-container" style={{ marginTop: 'var(--space-sm)' }}>
      <button
        className="btn btn-secondary btn-sm"
        onClick={handleBalance}
        disabled={disabled}
        data-testid="auto-balance-btn"
        style={{ width: '100%' }}
        title={isZeroAllocation ? 'Allocate points first to enable auto-balance' : ''}
      >
        {disabled && isZeroAllocation
          ? 'Auto-Balance Points (No Points Allocated)'
          : 'Auto-Balance Points'}
      </button>
    </div>
  );
}