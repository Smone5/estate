// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import AutoBalanceButton from './AutoBalanceButton';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('AutoBalanceButton Component', () => {
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      unallocatedPoints: 500,
      isSubmitted: false,
      is_hitl_suspended: false,
      valuations: {
        'asset-1': { points: 300 },
        'asset-2': { points: 200 },
      },
      autoBalancePoints: vi.fn(),
    };

    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') return selector(mockStoreState);
      return mockStoreState;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders auto-balance button', () => {
    render(<AutoBalanceButton />);
    expect(screen.getByTestId('auto-balance-btn')).toBeInTheDocument();
    expect(screen.getByText('Auto-Balance Points')).toBeInTheDocument();
  });

  it('calls autoBalancePoints when clicked', () => {
    render(<AutoBalanceButton />);
    fireEvent.click(screen.getByTestId('auto-balance-btn'));
    expect(mockStoreState.autoBalancePoints).toHaveBeenCalledTimes(1);
  });

  it('is disabled when zero points allocated', () => {
    mockStoreState.unallocatedPoints = 1000; // all 1000 unallocated
    render(<AutoBalanceButton />);
    const btn = screen.getByTestId('auto-balance-btn');
    expect(btn).toBeDisabled();
    expect(btn.textContent).toContain('No Points Allocated');
  });

  it('is disabled when submitted', () => {
    mockStoreState.isSubmitted = true;
    render(<AutoBalanceButton />);
    const btn = screen.getByTestId('auto-balance-btn');
    expect(btn).toBeDisabled();
  });

  it('is enabled when points are allocated and not submitted', () => {
    render(<AutoBalanceButton />);
    const btn = screen.getByTestId('auto-balance-btn');
    expect(btn).not.toBeDisabled();
  });

  it('is enabled during HITL suspension', () => {
    mockStoreState.is_hitl_suspended = true;
    render(<AutoBalanceButton />);
    const btn = screen.getByTestId('auto-balance-btn');
    expect(btn).not.toBeDisabled();
  });
});