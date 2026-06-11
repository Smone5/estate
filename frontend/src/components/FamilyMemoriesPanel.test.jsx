// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import FamilyMemoriesPanel from './FamilyMemoriesPanel';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('FamilyMemoriesPanel Component', () => {
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      valuations: {
        'asset-1': { points: 50, reasoning: 'This was grandmas clock', is_reasoning_shared: false },
        'asset-2': { points: 100, reasoning: 'A treasured family heirloom', is_reasoning_shared: true },
      },
      isPaused: false,
      isSubmitted: false,
      sessionStatus: 'ACTIVE',
      updateValuationText: vi.fn(),
    };

    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') return selector(mockStoreState);
      return mockStoreState;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders collapsed toggle button', () => {
    render(<FamilyMemoriesPanel assetId="asset-1" />);
    expect(screen.getByTestId('memories-toggle-btn')).toBeInTheDocument();
    expect(screen.getByText(/Family Memories & Stories/)).toBeInTheDocument();
    expect(screen.queryByTestId('memories-content')).not.toBeInTheDocument();
  });

  it('expands panel on toggle click', () => {
    render(<FamilyMemoriesPanel assetId="asset-1" />);
    fireEvent.click(screen.getByTestId('memories-toggle-btn'));
    expect(screen.getByTestId('memories-content')).toBeInTheDocument();
  });

  it('shows edit panel when session is active', () => {
    render(<FamilyMemoriesPanel assetId="asset-1" />);
    fireEvent.click(screen.getByTestId('memories-toggle-btn'));
    expect(screen.getByTestId('memories-edit-panel')).toBeInTheDocument();
    expect(screen.getByTestId('memory-textarea')).toBeInTheDocument();
    expect(screen.getByTestId('share-memory-checkbox')).toBeInTheDocument();
    expect(screen.getByTestId('save-memory-btn')).toBeInTheDocument();
  });

  it('saves memory when save button is clicked', () => {
    render(<FamilyMemoriesPanel assetId="asset-1" />);
    fireEvent.click(screen.getByTestId('memories-toggle-btn'));

    fireEvent.change(screen.getByTestId('memory-textarea'), {
      target: { value: 'New memory text' },
    });
    fireEvent.click(screen.getByTestId('share-memory-checkbox'));

    fireEvent.click(screen.getByTestId('save-memory-btn'));

    expect(mockStoreState.updateValuationText).toHaveBeenCalledWith(
      'asset-1', 'New memory text', true,
    );
  });

  it('displays shared memory block when is_reasoning_shared is true', () => {
    render(<FamilyMemoriesPanel assetId="asset-2" />);
    fireEvent.click(screen.getByTestId('memories-toggle-btn'));
    expect(screen.getByTestId('shared-memory-block')).toBeInTheDocument();
    // Text appears in both shared block and textarea; verify block is present
    const sharedBlock = screen.getByTestId('shared-memory-block');
    expect(sharedBlock.textContent).toContain('A treasured family heirloom');
  });

  it('shows empty state when no shared memories exist and not editing', () => {
    mockStoreState.sessionStatus = 'SETUP';
    render(<FamilyMemoriesPanel assetId="asset-1" />);
    fireEvent.click(screen.getByTestId('memories-toggle-btn'));
    expect(screen.getByTestId('memories-empty')).toBeInTheDocument();
  });

  it('locks editing when session is paused', () => {
    mockStoreState.isPaused = true;
    render(<FamilyMemoriesPanel assetId="asset-1" />);
    fireEvent.click(screen.getByTestId('memories-toggle-btn'));
    expect(screen.getByTestId('memories-locked-msg')).toBeInTheDocument();
    expect(screen.getByText(/locked while the session is paused/)).toBeInTheDocument();
    expect(screen.queryByTestId('memories-edit-panel')).not.toBeInTheDocument();
  });

  it('locks editing when valuations are submitted', () => {
    mockStoreState.isSubmitted = true;
    render(<FamilyMemoriesPanel assetId="asset-1" />);
    fireEvent.click(screen.getByTestId('memories-toggle-btn'));
    expect(screen.getByTestId('memories-locked-msg')).toBeInTheDocument();
    expect(screen.getByText(/locked after submission/)).toBeInTheDocument();
    expect(screen.queryByTestId('memories-edit-panel')).not.toBeInTheDocument();
  });
});