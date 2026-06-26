// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
// eslint-disable-next-line no-unused-vars
import React from 'react';
import '@testing-library/jest-dom';
import AdminDashboard from './AdminDashboard';
import { useMediationStore } from '../store/useMediationStore';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

vi.mock('../components/DashboardGuard', () => ({
  default: ({ children }) => <div data-testid="dashboard-guard">{children}</div>,
}));

vi.mock('../components/ForceAllocationConsole', () => ({
  default: () => <div data-testid="force-allocation-console" />,
}));

vi.mock('../components/AdminInventoryDashboard', () => ({
  default: () => <div data-testid="admin-inventory-dashboard" />,
}));

vi.mock('../components/AdminSessionControl', () => ({
  default: () => <div data-testid="admin-session-control" />,
}));

vi.mock('../components/AdminSessionLifecycleControls', () => ({
  default: () => <div data-testid="admin-session-lifecycle-controls" />,
}));

vi.mock('../components/AdminFinalDocumentsPanel', () => ({
  default: () => <div data-testid="admin-final-documents-panel" />,
}));

vi.mock('../components/AdminSetupWizard', () => ({
  default: () => <div data-testid="admin-setup-wizard" />,
}));

vi.mock('../components/BIP39RestorePanel', () => ({
  default: () => <div data-testid="bip39-restore-panel" />,
}));

vi.mock('../components/AdminHelpPortal', () => ({
  default: () => <div data-testid="admin-help-portal" />,
}));

vi.mock('../components/AdminAnnouncementConsole', () => ({
  default: () => <div data-testid="admin-announcement-console" />,
}));

vi.mock('../components/AdminSetupChecklist', () => ({
  default: () => <div data-testid="admin-setup-checklist" />,
}));

describe('AdminDashboard', () => {
  let mockStoreState;
  let localStorageData;

  beforeEach(() => {
    localStorageData = {};
    vi.stubGlobal('localStorage', {
      getItem: vi.fn((key) => localStorageData[key] ?? null),
      setItem: vi.fn((key, value) => {
        localStorageData[key] = String(value);
      }),
      removeItem: vi.fn((key) => {
        delete localStorageData[key];
      }),
    });

    mockStoreState = {
      sessionStatus: 'SETUP',
      isDeadlocked: false,
      session_id: null,
      userRole: null,
      isAuthenticated: false,
      setSession: vi.fn((sessionData) => {
        if (sessionData.isAuthenticated !== undefined) {
          mockStoreState.isAuthenticated = sessionData.isAuthenticated;
        }
        if (sessionData.user_role !== undefined) {
          mockStoreState.userRole = sessionData.user_role;
        }
        if (sessionData.userRole !== undefined) {
          mockStoreState.userRole = sessionData.userRole;
        }
        if (sessionData.session_id !== undefined) {
          mockStoreState.session_id = sessionData.session_id;
        }
        if (sessionData.status !== undefined) {
          mockStoreState.sessionStatus = sessionData.status;
        }
        if (sessionData.is_deadlocked !== undefined) {
          mockStoreState.isDeadlocked = sessionData.is_deadlocked;
        }
      }),
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
    vi.unstubAllGlobals();
  });

  it('restores an admin session from the secure cookie without clearing the saved console session', async () => {
    localStorage.setItem('admin_selected_session_id', 'session-1');
    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/auth/me') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            status: 'authenticated',
            user_id: 'admin-1',
            username: 'executor',
            role: 'ADMIN',
            session_id: null,
          }),
        });
      }
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 'session-1',
              title: 'Margaret Johnson Keepsakes',
              status: 'SETUP',
              is_deadlocked: false,
              is_paused: false,
              created_at: '2026-06-11T12:00:00Z',
            },
          ],
        });
      }
      if (url === '/api/sessions/session-1/assets' || url === '/api/sessions/session-1/heirs') {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<AdminDashboard />);

    expect(screen.getByText('Restoring Executor Session')).toBeInTheDocument();

    await waitFor(() => {
      expect(mockStoreState.setSession).toHaveBeenCalledWith(expect.objectContaining({
        isAuthenticated: true,
        user_role: 'ADMIN',
      }));
    });

    await waitFor(() => {
      expect(screen.getByText('Margaret Johnson Keepsakes')).toBeInTheDocument();
    });

    expect(localStorage.getItem('admin_selected_session_id')).toBe('session-1');
    expect(screen.queryByText('Executor Authentication')).not.toBeInTheDocument();
  });

  it('allows deleting a session and refreshes/clears console state if deleted session is active', async () => {
    mockStoreState.isAuthenticated = true;
    mockStoreState.userRole = 'ADMIN';
    mockStoreState.session_id = null;
    window.confirm = vi.fn(() => true);

    let deleteCalled = false;
    globalThis.fetch = vi.fn((url, options) => {
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 'session-1',
              title: 'Margaret Johnson Keepsakes',
              status: 'SETUP',
              is_deadlocked: false,
              is_paused: false,
              created_at: '2026-06-11T12:00:00Z',
            },
          ],
        });
      }
      if (url.includes('/api/sessions/session-1') && options?.method === 'DELETE') {
        deleteCalled = true;
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success' }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId('delete-session-session-1')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('delete-session-session-1'));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      expect(deleteCalled).toBe(true);
    });
  });

  it('allows inline renaming of a session and triggers PATCH api call', async () => {
    mockStoreState.isAuthenticated = true;
    mockStoreState.userRole = 'ADMIN';
    mockStoreState.session_id = null;

    let patchCalled = false;
    let patchBody = null;

    globalThis.fetch = vi.fn((url, options) => {
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 'session-1',
              title: 'Margaret Johnson Keepsakes',
              status: 'SETUP',
              is_deadlocked: false,
              is_paused: false,
              created_at: '2026-06-11T12:00:00Z',
            },
          ],
        });
      }
      if (url.includes('/api/sessions/session-1') && options?.method === 'PATCH') {
        patchCalled = true;
        patchBody = JSON.parse(options.body);
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 'session-1',
            title: patchBody.title,
          }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId('edit-session-btn-session-1')).toBeInTheDocument();
    });

    // Toggle edit mode
    fireEvent.click(screen.getByTestId('edit-session-btn-session-1'));

    // Verify input is present and has initial value
    const input = screen.getByTestId('edit-session-title-input-session-1');
    expect(input).toBeInTheDocument();
    expect(input.value).toBe('Margaret Johnson Keepsakes');

    // Change value and save
    fireEvent.change(input, { target: { value: 'New Estate Name' } });
    fireEvent.click(screen.getByTestId('save-session-btn-session-1'));

    await waitFor(() => {
      expect(patchCalled).toBe(true);
      expect(patchBody.title).toBe('New Estate Name');
    });

    // Verify UI has updated
    await waitFor(() => {
      expect(screen.getByText('New Estate Name')).toBeInTheDocument();
      expect(screen.queryByTestId('edit-session-title-input-session-1')).not.toBeInTheDocument();
    });
  });

  it('allows cancelling the inline renaming of a session', async () => {
    mockStoreState.isAuthenticated = true;
    mockStoreState.userRole = 'ADMIN';
    mockStoreState.session_id = null;

    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 'session-1',
              title: 'Margaret Johnson Keepsakes',
              status: 'SETUP',
              is_deadlocked: false,
              is_paused: false,
              created_at: '2026-06-11T12:00:00Z',
            },
          ],
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId('edit-session-btn-session-1')).toBeInTheDocument();
    });

    // Toggle edit mode
    fireEvent.click(screen.getByTestId('edit-session-btn-session-1'));
    expect(screen.getByTestId('edit-session-title-input-session-1')).toBeInTheDocument();

    // Cancel edit mode
    fireEvent.click(screen.getByTestId('cancel-session-btn-session-1'));

    expect(screen.queryByTestId('edit-session-title-input-session-1')).not.toBeInTheDocument();
    expect(screen.getByText('Margaret Johnson Keepsakes')).toBeInTheDocument();
  });

  it('supports searching, filtering, and paginating the session index', async () => {
    mockStoreState.isAuthenticated = true;
    mockStoreState.userRole = 'ADMIN';
    mockStoreState.session_id = null;

    const sessionRows = Array.from({ length: 9 }, (_, index) => ({
      id: `session-${index + 1}`,
      title: index === 0 ? 'Alpha Estate' : `Estate ${index + 1}`,
      status: index % 2 === 0 ? 'SETUP' : 'FINALIZED',
      is_deadlocked: false,
      is_paused: false,
      created_at: `2026-06-${String(index + 1).padStart(2, '0')}T12:00:00Z`,
    }));

    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => sessionRows,
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText('Estate 9')).toBeInTheDocument();
    });
    expect(screen.queryByText('Alpha Estate')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Next'));

    await waitFor(() => {
      expect(screen.getByText('Alpha Estate')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('session-search-input'), {
      target: { value: 'Estate 8' },
    });

    await waitFor(() => {
      expect(screen.getByText('Estate 8')).toBeInTheDocument();
      expect(screen.queryByText('Alpha Estate')).not.toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('session-status-filter'), {
      target: { value: 'SETUP' },
    });

    await waitFor(() => {
      expect(screen.queryByText('Estate 8')).not.toBeInTheDocument();
      expect(screen.getByText('No matching sessions')).toBeInTheDocument();
    });
  });

  it('calls POST /api/auth/logout and clears session state on logout', async () => {
    mockStoreState.isAuthenticated = true;
    mockStoreState.userRole = 'ADMIN';
    mockStoreState.session_id = null;
    localStorage.setItem('admin_selected_session_id', 'session-1');

    let logoutCalled = false;
    globalThis.fetch = vi.fn((url, options) => {
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      if (url === '/api/auth/logout' && options?.method === 'POST') {
        logoutCalled = true;
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'success' }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByText('Log Out')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Log Out'));

    await waitFor(() => {
      expect(logoutCalled).toBe(true);
    });

    expect(mockStoreState.setSession).toHaveBeenCalledWith({
      isAuthenticated: false,
      user_role: null,
      session_id: null,
    });
    expect(localStorage.getItem('admin_selected_session_id')).toBeNull();
  });

  it('shows session lifecycle controls on the overview for active sessions', async () => {
    mockStoreState.isAuthenticated = true;
    mockStoreState.userRole = 'ADMIN';
    mockStoreState.session_id = 'session-1';
    mockStoreState.sessionStatus = 'ACTIVE';

    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 'session-1',
              title: 'Margaret Johnson Keepsakes',
              status: 'ACTIVE',
              is_deadlocked: false,
              is_paused: false,
              created_at: '2026-06-11T12:00:00Z',
            },
          ],
        });
      }
      if (url === '/api/sessions/session-1/assets') {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      if (url === '/api/sessions/session-1/heirs') {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId('admin-session-lifecycle-controls')).toBeInTheDocument();
    });
  });

  it('shows final document downloads on the overview for finalized sessions', async () => {
    mockStoreState.isAuthenticated = true;
    mockStoreState.userRole = 'ADMIN';
    mockStoreState.session_id = 'session-1';
    mockStoreState.sessionStatus = 'FINALIZED';

    globalThis.fetch = vi.fn((url) => {
      if (url === '/api/sessions') {
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 'session-1',
              title: 'Margaret Johnson Keepsakes',
              status: 'FINALIZED',
              is_deadlocked: false,
              is_paused: false,
              created_at: '2026-06-11T12:00:00Z',
            },
          ],
        });
      }
      if (url === '/api/sessions/session-1/assets') {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      if (url === '/api/sessions/session-1/heirs') {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    });

    render(<AdminDashboard />);

    await waitFor(() => {
      expect(screen.getByTestId('admin-final-documents-panel')).toBeInTheDocument();
    });
  });
});
