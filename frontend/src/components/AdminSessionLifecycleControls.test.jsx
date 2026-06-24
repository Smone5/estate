// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import '@testing-library/jest-dom';
import AdminSessionLifecycleControls from './AdminSessionLifecycleControls';
import { useMediationStore } from '../store/useMediationStore';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('AdminSessionLifecycleControls', () => {
  const sessionId = 'session-123';
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      sessionStatus: 'SETUP',
      isPaused: false,
      loadSessionDetails: vi.fn(),
    };

    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') {
        return selector(mockStoreState);
      }
      return mockStoreState;
    });

    global.fetch = vi.fn();
    window.confirm = vi.fn(() => true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders setup phase status banner with launch button', () => {
    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    expect(screen.getByText(/Session Status:/)).toBeInTheDocument();
    expect(screen.getByText('SETUP')).toBeInTheDocument();
    expect(screen.getByTestId('launch-session-btn')).toBeInTheDocument();
  });

  it('renders active phase with pause and finalize buttons', () => {
    mockStoreState.sessionStatus = 'ACTIVE';

    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    expect(screen.getByTestId('pause-session-btn')).toBeInTheDocument();
    expect(screen.getByTestId('finalize-session-btn')).toBeInTheDocument();
    expect(screen.queryByTestId('launch-session-btn')).not.toBeInTheDocument();
  });

  it('renders unpause button when paused', () => {
    mockStoreState.sessionStatus = 'ACTIVE';
    mockStoreState.isPaused = true;

    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    expect(screen.getByTestId('unpause-session-btn')).toBeInTheDocument();
    expect(screen.getByText(/Paused/)).toBeInTheDocument();
    expect(screen.queryByTestId('pause-session-btn')).not.toBeInTheDocument();
  });

  it('launches session and refreshes details', async () => {
    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    fireEvent.click(screen.getByTestId('launch-session-btn'));

    await waitFor(() => {
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(screen.getByText(/Session launched/)).toBeInTheDocument();
    });
  });

  it('pauses session and refreshes details', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';

    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    fireEvent.click(screen.getByTestId('pause-session-btn'));

    await waitFor(() => {
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(screen.getByText(/Session paused/)).toBeInTheDocument();
    });
  });

  it('unpauses session and refreshes details', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';
    mockStoreState.isPaused = true;

    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    fireEvent.click(screen.getByTestId('unpause-session-btn'));

    await waitFor(() => {
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(screen.getByText(/Session unpaused/)).toBeInTheDocument();
    });
  });

  it('finalizes session and refreshes details', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';

    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    fireEvent.click(screen.getByTestId('finalize-session-btn'));

    await waitFor(() => {
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(screen.getByText(/Session finalized/)).toBeInTheDocument();
    });
  });

  it('displays error banner on failed API call', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';

    render(<AdminSessionLifecycleControls sessionId={sessionId} />);

    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Server error' }),
      status: 500,
    });

    fireEvent.click(screen.getByTestId('pause-session-btn'));

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument();
    });
  });
});
