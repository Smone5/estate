// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
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
    // Simulate the real restoreHeirSession flipping isAuthenticated once
    // the cookie resolves, same as the store implementation does.
    mockStoreState.restoreHeirSession = vi.fn().mockImplementation(async () => {
      mockStoreState.isAuthenticated = true;
      mockStoreState.session_id = 'session-1';
    });

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <DashboardGuard variant="heir">
          <div>Heir dashboard</div>
        </DashboardGuard>
      </MemoryRouter>,
    );

    expect(screen.getByText('Restoring Dashboard')).toBeInTheDocument();

    await waitFor(() => {
      expect(mockStoreState.restoreHeirSession).toHaveBeenCalledTimes(1);
    });
  });

  it('redirects to /login when the cookie does not resolve to a valid Heir session', async () => {
    mockStoreState.isAuthenticated = false;
    mockStoreState.session_id = null;
    // Simulate an expired/missing cookie: restoreHeirSession resolves
    // without ever setting isAuthenticated.
    mockStoreState.restoreHeirSession = vi.fn().mockResolvedValue();

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route
            path="/dashboard"
            element={(
              <DashboardGuard variant="heir">
                <div>Heir dashboard</div>
              </DashboardGuard>
            )}
          />
          <Route path="/login" element={<div>Login Page</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('Restoring Dashboard')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Login Page')).toBeInTheDocument();
    });
  });

  it('polls heir profile and session state while the dashboard is open', async () => {
    vi.useFakeTimers();

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <DashboardGuard variant="heir">
          <div>Heir dashboard</div>
        </DashboardGuard>
      </MemoryRouter>,
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
      <MemoryRouter initialEntries={['/dashboard']}>
        <DashboardGuard variant="heir">
          <div>Heir dashboard</div>
        </DashboardGuard>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('support-notice-banner')).toHaveTextContent('The Executor replied');

    fireEvent.click(screen.getByTestId('view-support-reply-btn'));
    expect(mockStoreState.clearLatestSupportNotice).toHaveBeenCalledTimes(1);
  });

  it('renders children directly and bypasses all banners/gates for variant="admin"', () => {
    mockStoreState.sessionStatus = 'SETUP';
    mockStoreState.userStatus = 'PROFILE_HOLD';

    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <DashboardGuard variant="admin">
          <div data-testid="admin-content">Admin console content</div>
        </DashboardGuard>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('admin-content')).toBeInTheDocument();
    expect(screen.queryByText(/AI Mediator Agent/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Welcome! The Executor is currently setting up/)).not.toBeInTheDocument();
  });
});
