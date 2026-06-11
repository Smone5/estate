// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import '@testing-library/jest-dom';
import AdminAnnouncementConsole from './AdminAnnouncementConsole';
import AnnouncementAlertBanner from './AnnouncementAlertBanner';
import AnnouncementLoginModal from './AnnouncementLoginModal';

const makeStorageMock = () => {
  let store = {};
  return {
    getItem: vi.fn((key) => store[key] || null),
    setItem: vi.fn((key, value) => {
      store[key] = value.toString();
    }),
    removeItem: vi.fn((key) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
  };
};

const mockLocalStorage = makeStorageMock();
const mockSessionStorage = makeStorageMock();

Object.defineProperty(window, 'localStorage', {
  value: mockLocalStorage,
  writable: true,
});
Object.defineProperty(window, 'sessionStorage', {
  value: mockSessionStorage,
  writable: true,
});

// Mock Zustand store state
const mockStoreState = {
  announcement: null,
  announcement_updated_at: null,
  isAuthenticated: false,
  userRole: 'HEIR',
  sessionStatus: 'ACTIVE',
  setSession: vi.fn(),
};

vi.mock('../store/useMediationStore', () => {
  const useStoreMock = (selector) => {
    if (typeof selector === 'function') {
      return selector(mockStoreState);
    }
    return mockStoreState;
  };
  useStoreMock.getState = () => mockStoreState;
  return {
    useMediationStore: useStoreMock,
  };
});

describe('Announcement Components', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
    mockStoreState.announcement = null;
    mockStoreState.announcement_updated_at = null;
    mockStoreState.isAuthenticated = false;
    mockStoreState.userRole = 'HEIR';
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  describe('AdminAnnouncementConsole', () => {
    it('pre-populates textarea with current announcement', () => {
      mockStoreState.announcement = 'Hello family';
      render(<AdminAnnouncementConsole sessionId="session-123" />);
      const textarea = screen.getByPlaceholderText(/Enter announcement text/i);
      expect(textarea.value).toBe('Hello family');
    });

    it('submits a new announcement on Broadcast', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'session-123',
          announcement: 'Important notice',
          announcement_updated_at: '2026-06-11T12:00:00Z',
        }),
      });

      render(<AdminAnnouncementConsole sessionId="session-123" />);
      const textarea = screen.getByPlaceholderText(/Enter announcement text/i);
      fireEvent.change(textarea, { target: { value: 'Important notice' } });

      const broadcastBtn = screen.getByRole('button', { name: /Broadcast Announcement/i });
      fireEvent.click(broadcastBtn);

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/sessions/session-123/announcement', expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ announcement: 'Important notice' }),
        }));
        expect(mockStoreState.setSession).toHaveBeenCalled();
        expect(screen.getByText('Announcement broadcasted successfully.')).toBeInTheDocument();
      });
    });

    it('clears active announcement on Clear', async () => {
      mockStoreState.announcement = 'Hello family';
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: 'session-123',
          announcement: null,
          announcement_updated_at: null,
        }),
      });

      render(<AdminAnnouncementConsole sessionId="session-123" />);
      const clearBtn = screen.getByRole('button', { name: /Clear Announcement/i });
      fireEvent.click(clearBtn);

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith('/api/sessions/session-123/announcement', expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ announcement: null }),
        }));
        expect(mockStoreState.setSession).toHaveBeenCalled();
        expect(screen.getByText('Announcement cleared successfully.')).toBeInTheDocument();
      });
    });
  });

  describe('AnnouncementAlertBanner', () => {
    it('renders nothing when there is no announcement', () => {
      render(<AnnouncementAlertBanner />);
      expect(screen.queryByTestId('announcement-banner')).not.toBeInTheDocument();
    });

    it('renders banner when announcement exists and is not dismissed', () => {
      mockStoreState.announcement = 'Dinner is ready';
      mockStoreState.announcement_updated_at = '2026-06-11T12:00:00Z';
      render(<AnnouncementAlertBanner />);
      expect(screen.getByTestId('announcement-banner')).toBeInTheDocument();
      expect(screen.getByText('Dinner is ready')).toBeInTheDocument();
    });

    it('dismisses the banner when dismiss button is clicked', () => {
      mockStoreState.announcement = 'Dinner is ready';
      mockStoreState.announcement_updated_at = '2026-06-11T12:00:00Z';
      render(<AnnouncementAlertBanner />);
      
      const dismissBtn = screen.getByTestId('announcement-dismiss-btn');
      fireEvent.click(dismissBtn);

      expect(screen.queryByTestId('announcement-banner')).not.toBeInTheDocument();
      expect(sessionStorage.getItem('announcement_dismissed_2026-06-11T12:00:00Z')).toBe('true');
    });
  });

  describe('AnnouncementLoginModal', () => {
    it('renders nothing when not authenticated', () => {
      mockStoreState.announcement = 'Important Notice';
      mockStoreState.announcement_updated_at = '2026-06-11T12:00:00Z';
      mockStoreState.isAuthenticated = false;
      render(<AnnouncementLoginModal />);
      expect(screen.queryByTestId('announcement-modal')).not.toBeInTheDocument();
    });

    it('renders modal when authenticated heir and not acknowledged', () => {
      mockStoreState.announcement = 'Important Notice';
      mockStoreState.announcement_updated_at = '2026-06-11T12:00:00Z';
      mockStoreState.isAuthenticated = true;
      mockStoreState.userRole = 'HEIR';
      render(<AnnouncementLoginModal />);
      expect(screen.getByTestId('announcement-modal')).toBeInTheDocument();
      expect(screen.getByText('Important Notice')).toBeInTheDocument();
    });

    it('does not render modal when already acknowledged', () => {
      mockStoreState.announcement = 'Important Notice';
      mockStoreState.announcement_updated_at = '2026-06-11T12:00:00Z';
      mockStoreState.isAuthenticated = true;
      mockStoreState.userRole = 'HEIR';
      localStorage.setItem('announcement_ack_2026-06-11T12:00:00Z', 'true');
      render(<AnnouncementLoginModal />);
      expect(screen.queryByTestId('announcement-modal')).not.toBeInTheDocument();
    });

    it('acknowledges and closes when button is clicked', () => {
      mockStoreState.announcement = 'Important Notice';
      mockStoreState.announcement_updated_at = '2026-06-11T12:00:00Z';
      mockStoreState.isAuthenticated = true;
      mockStoreState.userRole = 'HEIR';
      render(<AnnouncementLoginModal />);

      const ackBtn = screen.getByTestId('announcement-ack-btn');
      fireEvent.click(ackBtn);

      expect(screen.queryByTestId('announcement-modal')).not.toBeInTheDocument();
      expect(localStorage.getItem('announcement_ack_2026-06-11T12:00:00Z')).toBe('true');
    });
  });
});
