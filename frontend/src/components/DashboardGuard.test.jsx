// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardGuard from './DashboardGuard';
import { useMediationStore } from '../store/useMediationStore';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

vi.mock('./AnnouncementAlertBanner', () => ({
  default: () => <div data-testid="announcement-alert" />,
}));

vi.mock('./AnnouncementLoginModal', () => ({
  default: () => <div data-testid="announcement-modal" />,
}));

vi.mock('./AbstentionWaitScreen', () => ({
  default: () => <div data-testid="abstention-wait" />,
}));

describe('DashboardGuard', () => {
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      sessionStatus: 'SETUP',
      userStatus: 'PROFILE_HOLD',
      isPaused: false,
      isDeadlocked: false,
      is_hitl_suspended: false,
      isSubmitted: false,
      isAuthenticated: true,
      session_id: 'session-1',
      loadSessionDetails: vi.fn().mockResolvedValue(),
      loadProfile: vi.fn().mockResolvedValue(),
      restoreHeirSession: vi.fn().mockResolvedValue(),
      loadAssets: vi.fn().mockResolvedValue(),
      loadValuations: vi.fn().mockResolvedValue(),
      latestSupportNotice: null,
      clearLatestSupportNotice: vi.fn(),
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

  it('restores an heir dashboard from the secure cookie on hard refresh', async () => {
    mockStoreState.isAuthenticated = false;
    mockStoreState.session_id = null;

    render(
      <DashboardGuard variant="heir">
        <div>Heir dashboard</div>
      </DashboardGuard>,
    );

    expect(screen.getByText('Restoring Dashboard')).toBeInTheDocument();

    await waitFor(() => {
      expect(mockStoreState.restoreHeirSession).toHaveBeenCalledTimes(1);
    });
  });

  it('polls heir profile and session state while the dashboard is open', async () => {
    vi.useFakeTimers();

    render(
      <DashboardGuard variant="heir">
        <div>Heir dashboard</div>
      </DashboardGuard>,
    );

    expect(mockStoreState.loadProfile).toHaveBeenCalledTimes(1);
    expect(mockStoreState.loadSessionDetails).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    expect(mockStoreState.loadProfile).toHaveBeenCalledTimes(2);
    expect(mockStoreState.loadSessionDetails).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });

  it('shows a realtime executor reply notice to heirs', () => {
    mockStoreState.latestSupportNotice = {
      type: 'reply',
      ticket_id: 'ticket-1',
      message: 'The Executor replied to your message.',
      timestamp: '2026-06-16T12:00:00Z',
    };

    render(
      <DashboardGuard variant="heir">
        <div>Heir dashboard</div>
      </DashboardGuard>,
    );

    expect(screen.getByTestId('support-notice-banner')).toHaveTextContent('The Executor replied');

    fireEvent.click(screen.getByTestId('view-support-reply-btn'));
    expect(mockStoreState.clearLatestSupportNotice).toHaveBeenCalledTimes(1);
  });
});
