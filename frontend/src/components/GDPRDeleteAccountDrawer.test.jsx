// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import GDPRDeleteAccountDrawer from './GDPRDeleteAccountDrawer';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('GDPRDeleteAccountDrawer Component', () => {
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      legal_first_name: 'Alice',
      deleteAccount: vi.fn().mockResolvedValue(),
    };

    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') {
        return selector(mockStoreState);
      }
      return mockStoreState;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the trigger button', () => {
    render(<GDPRDeleteAccountDrawer />);
    expect(screen.getByTestId('delete-account-trigger-btn')).toBeInTheDocument();
    expect(screen.getByText('Delete My Account & Data')).toBeInTheDocument();
  });

  it('opens the drawer when trigger is clicked', () => {
    render(<GDPRDeleteAccountDrawer />);

    fireEvent.click(screen.getByTestId('delete-account-trigger-btn'));

    expect(screen.getByTestId('delete-account-drawer')).toBeInTheDocument();
    expect(screen.getByText('Delete Account & Data')).toBeInTheDocument();
    expect(screen.getByTestId('delete-confirm-input')).toBeInTheDocument();
    expect(screen.getByTestId('delete-confirm-btn')).toBeInTheDocument();
    expect(screen.getByTestId('delete-cancel-btn')).toBeInTheDocument();
  });

  it('disables the delete button until username matches exactly', () => {
    render(<GDPRDeleteAccountDrawer />);

    fireEvent.click(screen.getByTestId('delete-account-trigger-btn'));

    const confirmBtn = screen.getByTestId('delete-confirm-btn');
    expect(confirmBtn).toBeDisabled();

    const input = screen.getByTestId('delete-confirm-input');
    fireEvent.change(input, { target: { value: 'Bob' } });

    expect(confirmBtn).toBeDisabled();

    fireEvent.change(input, { target: { value: 'Alice' } });

    expect(confirmBtn).not.toBeDisabled();
  });

  it('uses case-sensitive matching', () => {
    render(<GDPRDeleteAccountDrawer />);

    fireEvent.click(screen.getByTestId('delete-account-trigger-btn'));

    const input = screen.getByTestId('delete-confirm-input');
    fireEvent.change(input, { target: { value: 'alice' } });

    const confirmBtn = screen.getByTestId('delete-confirm-btn');
    expect(confirmBtn).toBeDisabled();
  });

  it('calls deleteAccount and closes drawer on successful deletion', async () => {
    render(<GDPRDeleteAccountDrawer />);

    fireEvent.click(screen.getByTestId('delete-account-trigger-btn'));

    const input = screen.getByTestId('delete-confirm-input');
    fireEvent.change(input, { target: { value: 'Alice' } });

    const confirmBtn = screen.getByTestId('delete-confirm-btn');
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockStoreState.deleteAccount).toHaveBeenCalledTimes(1);
      expect(screen.queryByTestId('delete-account-drawer')).not.toBeInTheDocument();
    });
  });

  it('shows error on deletion failure', async () => {
    mockStoreState.deleteAccount.mockRejectedValueOnce(new Error('Deletion failed'));

    render(<GDPRDeleteAccountDrawer />);

    fireEvent.click(screen.getByTestId('delete-account-trigger-btn'));

    const input = screen.getByTestId('delete-confirm-input');
    fireEvent.change(input, { target: { value: 'Alice' } });

    const confirmBtn = screen.getByTestId('delete-confirm-btn');
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(screen.getByText('Deletion failed')).toBeInTheDocument();
      // Drawer should still be open
      expect(screen.getByTestId('delete-account-drawer')).toBeInTheDocument();
    });
  });

  it('closes the drawer on cancel button click', () => {
    render(<GDPRDeleteAccountDrawer />);

    fireEvent.click(screen.getByTestId('delete-account-trigger-btn'));

    expect(screen.getByTestId('delete-account-drawer')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('delete-cancel-btn'));

    expect(screen.queryByTestId('delete-account-drawer')).not.toBeInTheDocument();
  });

  it('shows warning text with GDPR Article 17 reference', () => {
    render(<GDPRDeleteAccountDrawer />);

    fireEvent.click(screen.getByTestId('delete-account-trigger-btn'));

    expect(screen.getByText(/GDPR Article 17/)).toBeInTheDocument();
    expect(screen.getByText(/Right to Erasure/)).toBeInTheDocument();
  });
});