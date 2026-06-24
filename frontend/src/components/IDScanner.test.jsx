// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import IDScanner from './IDScanner';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('IDScanner Component', () => {
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      userStatus: 'PROFILE_HOLD',
      id_scan_uri: null,
      loadProfile: vi.fn().mockResolvedValue(),
    };

    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') {
        return selector(mockStoreState);
      }
      return mockStoreState;
    });

    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders only while heir is on profile hold', () => {
    render(<IDScanner />);
    expect(screen.getByText('Government ID Verification')).toBeInTheDocument();

    mockStoreState.userStatus = 'ACTIVE';
    const { container } = render(<IDScanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows executor review state after a successful ID upload', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'success' }),
    });

    render(<IDScanner />);

    const fileInput = screen.getByLabelText('Upload government ID scan');
    const file = new File(['fake-id'], 'license.jpg', { type: 'image/jpeg' });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/ID scan submitted for Executor review/)).toBeInTheDocument();
      expect(mockStoreState.loadProfile).toHaveBeenCalledTimes(1);
    });

    expect(screen.queryByText(/Drop ID Scan \/ Photo Here/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Scan ID with Camera/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Choose File/i })).not.toBeInTheDocument();
  });

  it('keeps the executor review state after profile reload when an ID scan exists', () => {
    mockStoreState.id_scan_uri = 'static/uploads/identities/test-scan';

    render(<IDScanner />);

    expect(screen.getByText('ID Submitted for Executor Review')).toBeInTheDocument();
    expect(screen.getByText(/ID scan submitted for Executor review/)).toBeInTheDocument();
    expect(screen.queryByText(/Drop ID Scan \/ Photo Here/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Scan ID with Camera/i })).not.toBeInTheDocument();
  });
});
