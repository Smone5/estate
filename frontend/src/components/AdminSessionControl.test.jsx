// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import AdminSessionControl from './AdminSessionControl';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('AdminSessionControl Component', () => {
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

    // Mock clipboard
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: vi.fn().mockResolvedValue() },
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Session Status Banner ───────────────────────────────────────────────
  it('renders setup phase status banner with launch button', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByText(/Session Status:/)).toBeInTheDocument();
      expect(screen.getByText('SETUP')).toBeInTheDocument();
      expect(screen.getByTestId('launch-session-btn')).toBeInTheDocument();
    });
  });

  it('renders active phase with pause and finalize buttons', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('pause-session-btn')).toBeInTheDocument();
      expect(screen.getByTestId('finalize-session-btn')).toBeInTheDocument();
      expect(screen.queryByTestId('launch-session-btn')).not.toBeInTheDocument();
    });
  });

  it('renders unpause button when paused', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';
    mockStoreState.isPaused = true;
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('unpause-session-btn')).toBeInTheDocument();
      expect(screen.getByText(/Paused/)).toBeInTheDocument();
      expect(screen.queryByTestId('pause-session-btn')).not.toBeInTheDocument();
    });
  });

  // ── Session Controls ────────────────────────────────────────────────────
  it('launches session and refreshes details', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] }); // heirs

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('launch-session-btn')).toBeInTheDocument();
    });

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    fireEvent.click(screen.getByTestId('launch-session-btn'));

    await waitFor(() => {
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(screen.getByText(/Session launched/)).toBeInTheDocument();
    });
  });

  it('pauses session and refreshes details', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] }); // heirs

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('pause-session-btn')).toBeInTheDocument();
    });

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
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] }); // heirs

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('unpause-session-btn')).toBeInTheDocument();
    });

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    fireEvent.click(screen.getByTestId('unpause-session-btn'));

    await waitFor(() => {
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(screen.getByText(/Session unpaused/)).toBeInTheDocument();
    });
  });

  it('finalizes session and refreshes details', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] }); // heirs

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('finalize-session-btn')).toBeInTheDocument();
    });

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

    fireEvent.click(screen.getByTestId('finalize-session-btn'));

    await waitFor(() => {
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(screen.getByText(/Session finalized/)).toBeInTheDocument();
    });
  });

  // ── Heir Registration ───────────────────────────────────────────────────
  it('registers a new heir and refreshes the list', async () => {
    // Initial empty heir list
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('heir-reg-username')).toBeInTheDocument();
    });

    // Fill form
    fireEvent.change(screen.getByTestId('heir-reg-username'), {
      target: { value: 'Alice Smith' },
    });
    fireEvent.change(screen.getByTestId('heir-reg-email'), {
      target: { value: 'alice@example.com' },
    });
    fireEvent.change(screen.getByTestId('heir-reg-phone'), {
      target: { value: '555-1234' },
    });
    fireEvent.change(screen.getByTestId('heir-reg-address'), {
      target: { value: '123 Main St' },
    });

    // POST mock
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'heir-1' }) });
    // Refresh mock
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 'heir-1',
          username: 'Alice Smith',
          email: 'alice@example.com',
          phone: '555-1234',
          physical_address: '123 Main St',
          user_status: 'PENDING',
          invite_token: 'tok-1234-abcd',
          invite_dispatched_at: null,
          invite_token_expires_at: null,
        },
      ],
    });

    fireEvent.click(screen.getByTestId('heir-reg-submit'));

    await waitFor(() => {
      expect(screen.getByText(/Heir registered successfully/)).toBeInTheDocument();
      expect(screen.getByText('Alice Smith')).toBeInTheDocument();
    });
  });

  it('shows validation error when required fields are empty', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('heir-reg-submit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('heir-reg-submit'));

    await waitFor(() => {
      expect(
        screen.getByText(/Display Name and Email are required/),
      ).toBeInTheDocument();
    });
  });

  // ── Heir Monitor Table ──────────────────────────────────────────────────
  it('renders heir monitor table with status checkmarks', async () => {
    const mockHeirs = [
      {
        id: 'heir-1',
        username: 'Alice',
        email: 'alice@a.com',
        phone: '555-1111',
        physical_address: '123 A St',
        user_status: 'SUBMITTED',
        invite_token: 'aaa-bbb-ccc',
        invite_dispatched_at: '2026-01-01T12:00:00Z',
        invite_token_expires_at: '2026-01-15T12:00:00Z',
      },
      {
        id: 'heir-2',
        username: 'Bob',
        email: 'bob@b.com',
        phone: null,
        physical_address: null,
        user_status: 'PENDING',
        invite_token: null,
        invite_dispatched_at: null,
        invite_token_expires_at: null,
      },
    ];

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockHeirs,
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('heir-monitor-table')).toBeInTheDocument();
      expect(screen.getByText('Alice')).toBeInTheDocument();
      expect(screen.getByText('Bob')).toBeInTheDocument();
      expect(screen.getByText('✅')).toBeInTheDocument();
      expect(screen.getByText('⏳ Pending')).toBeInTheDocument();
    });
  });

  // ── Invite Actions ──────────────────────────────────────────────────────
  it('sends invite and refreshes list', async () => {
    const mockHeirs = [
      {
        id: 'heir-1',
        username: 'Alice',
        email: 'alice@a.com',
        phone: null,
        physical_address: null,
        user_status: 'PENDING',
        invite_token: 'tok-1234',
        invite_dispatched_at: null,
        invite_token_expires_at: '2026-02-01T00:00:00Z',
      },
    ];

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockHeirs,
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('send-invite-heir-1')).toBeInTheDocument();
    });

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => mockHeirs });

    fireEvent.click(screen.getByTestId('send-invite-heir-1'));

    await waitFor(() => {
      expect(screen.getByText(/Invitation email dispatched/)).toBeInTheDocument();
    });
  });

  it('regenerates token and refreshes list', async () => {
    const mockHeirs = [
      {
        id: 'heir-1',
        username: 'Alice',
        email: 'alice@a.com',
        phone: null,
        physical_address: null,
        user_status: 'PENDING',
        invite_token: 'old-token',
        invite_dispatched_at: null,
        invite_token_expires_at: null,
      },
    ];

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockHeirs,
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('regen-token-heir-1')).toBeInTheDocument();
    });

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => mockHeirs });

    fireEvent.click(screen.getByTestId('regen-token-heir-1'));

    await waitFor(() => {
      expect(screen.getByText(/Invite token regenerated/)).toBeInTheDocument();
    });
  });

  // ── Delete Heir ─────────────────────────────────────────────────────────
  it('deletes heir after confirmation', async () => {
    const mockHeirs = [
      {
        id: 'heir-del',
        username: 'Charlie',
        email: 'charlie@c.com',
        phone: null,
        physical_address: null,
        user_status: 'PENDING',
        invite_token: 'tok-xxx',
        invite_dispatched_at: null,
        invite_token_expires_at: null,
      },
    ];

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockHeirs,
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('delete-heir-heir-del')).toBeInTheDocument();
    });

    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] });

    fireEvent.click(screen.getByTestId('delete-heir-heir-del'));

    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringContaining('Charlie'),
    );

    await waitFor(() => {
      expect(screen.getByText(/Heir deleted and PII purged/)).toBeInTheDocument();
      expect(screen.queryByText('Charlie')).not.toBeInTheDocument();
    });
  });

  // ── Error Handling ──────────────────────────────────────────────────────
  it('displays error banner on failed API call', async () => {
    mockStoreState.sessionStatus = 'ACTIVE';
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('pause-session-btn')).toBeInTheDocument();
    });

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

  // ── Empty State ─────────────────────────────────────────────────────────
  it('shows empty state when no heirs exist', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [] });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(
        screen.getByText(/No heirs registered yet/),
      ).toBeInTheDocument();
    });
  });

  // ── Copy Token ──────────────────────────────────────────────────────────
  it('copies invite token to clipboard', async () => {
    const mockHeirs = [
      {
        id: 'heir-1',
        username: 'Alice',
        email: 'alice@a.com',
        phone: null,
        physical_address: null,
        user_status: 'PENDING',
        invite_token: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        invite_dispatched_at: null,
        invite_token_expires_at: null,
      },
    ];

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockHeirs,
    });

    render(<AdminSessionControl sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('copy-token-heir-1')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('copy-token-heir-1'));

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      );
      expect(screen.getByText(/Token copied/)).toBeInTheDocument();
    });
  });
});