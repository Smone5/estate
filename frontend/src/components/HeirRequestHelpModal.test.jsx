// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import HeirRequestHelpModal from './HeirRequestHelpModal';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('HeirRequestHelpModal Component', () => {
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = { session_id: 'session-123' };
    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') return selector(mockStoreState);
      return mockStoreState;
    });
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the help modal', () => {
    render(<HeirRequestHelpModal onClose={() => {}} />);
    expect(screen.getByTestId('request-help-modal')).toBeInTheDocument();
    expect(screen.getByText(/Need Assistance/)).toBeInTheDocument();
    expect(screen.getByTestId('help-message-textarea')).toBeInTheDocument();
    expect(screen.getByTestId('help-send-btn')).toBeInTheDocument();
    expect(screen.getByTestId('help-cancel-btn')).toBeInTheDocument();
  });

  it('disables send button for short messages (<5 chars)', () => {
    render(<HeirRequestHelpModal onClose={() => {}} />);
    const btn = screen.getByTestId('help-send-btn');
    expect(btn).toBeDisabled();
  });

  it('enables send button when message is valid', () => {
    render(<HeirRequestHelpModal onClose={() => {}} />);
    fireEvent.change(screen.getByTestId('help-message-textarea'), {
      target: { value: 'I need help with an asset' },
    });
    expect(screen.getByTestId('help-send-btn')).not.toBeDisabled();
  });

  it('shows character counter', () => {
    render(<HeirRequestHelpModal onClose={() => {}} />);
    fireEvent.change(screen.getByTestId('help-message-textarea'), {
      target: { value: 'Hello' },
    });
    expect(screen.getByTestId('help-char-counter').textContent).toContain('5 / 1000');
  });

  it('sends message and shows confirmation', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    render(<HeirRequestHelpModal onClose={() => {}} />);
    fireEvent.change(screen.getByTestId('help-message-textarea'), {
      target: { value: 'I need assistance please' },
    });
    fireEvent.click(screen.getByTestId('help-send-btn'));

    await waitFor(() => {
      expect(screen.getByText('Message Delivered')).toBeInTheDocument();
    });
  });

  it('calls onClose when cancel is clicked', () => {
    const onClose = vi.fn();
    render(<HeirRequestHelpModal onClose={onClose} />);
    fireEvent.click(screen.getByTestId('help-cancel-btn'));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows error banner on API failure', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Server error' }),
      status: 500,
    });

    render(<HeirRequestHelpModal onClose={() => {}} />);
    fireEvent.change(screen.getByTestId('help-message-textarea'), {
      target: { value: 'Testing help request' },
    });
    fireEvent.click(screen.getByTestId('help-send-btn'));

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument();
    });
  });
});