// @vitest-environment jsdom
import React, { act } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import AdminCommunicationsPanel from './AdminCommunicationsPanel';
import { useMediationStore } from '../store/useMediationStore';

const SESSION_ID = 'session-123';
const HEIR_ID = 'heir-123';

const openTicket = {
  id: 'ticket-1',
  session_id: SESSION_ID,
  heir_id: HEIR_ID,
  username: 'aaron',
  legal_name: 'Aaron Melton',
  message: 'Can you clarify who receives the clock?',
  admin_response: null,
  initiator_role: 'HEIR',
  status: 'OPEN',
  created_at: '2026-06-16T12:00:00Z',
  responded_at: null,
  resolved_at: null,
  responded_by_username: null,
};

const baseHeirs = [
  {
    id: HEIR_ID,
    role: 'HEIR',
    username: 'aaron',
    email: 'aaron@example.com',
    legal_first_name: 'Aaron',
    legal_last_name: 'Melton',
    legal_middle_name: '',
  },
];

describe('AdminCommunicationsPanel', () => {
  beforeEach(() => {
    useMediationStore.setState({
      supportRefreshToken: 0,
      openSupportRequests: [],
      latestSupportNotice: null,
    });
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads tickets and displays heir messages as incoming bubbles', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => [openTicket] });

    render(<AdminCommunicationsPanel sessionId={SESSION_ID} heirs={baseHeirs} />);

    expect((await screen.findAllByText('Aaron Melton')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Can you clarify who receives the clock?').length).toBeGreaterThan(0);
  });

  it('sends an executor reply and shows it as an outgoing bubble', async () => {
    const repliedTicket = {
      ...openTicket,
      status: 'RESPONDED',
      admin_response: 'Yes, the clock goes to Aaron.',
      responded_at: '2026-06-16T12:05:00Z',
      responded_by_username: 'executor',
    };

    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => [openTicket] })
      .mockResolvedValueOnce({ ok: true, json: async () => repliedTicket });

    render(<AdminCommunicationsPanel sessionId={SESSION_ID} heirs={baseHeirs} />);

    // Wait for the heir message to appear
    expect((await screen.findAllByText('Can you clarify who receives the clock?')).length).toBeGreaterThan(0);

    // Type in the integrated composer and send
    fireEvent.change(screen.getByTestId('executor-reply-textarea'), {
      target: { value: 'Yes, the clock goes to Aaron.' },
    });
    fireEvent.click(screen.getByTestId('send-executor-reply-btn'));

    await waitFor(() => {
      // Should call the /reply endpoint (not /direct) because there's an open heir ticket
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/help/ticket-1/reply',
        expect.objectContaining({ method: 'POST' }),
      );
      // Admin reply should appear as its own bubble
      expect(screen.getByText('Yes, the clock goes to Aaron.')).toBeInTheDocument();
    });
  });

  it('sends a new direct message when there are no open heir tickets', async () => {
    const directTicket = {
      id: 'ticket-direct-1',
      session_id: SESSION_ID,
      heir_id: HEIR_ID,
      message: 'Executor initiated direct message.',
      admin_response: 'Please confirm your pickup window.',
      initiator_role: 'ADMIN',
      status: 'RESPONDED',
      created_at: '2026-06-16T12:15:00Z',
      responded_at: '2026-06-16T12:15:00Z',
      responded_by_username: 'executor',
    };

    // No tickets initially, so no open heir request → next send should use /direct
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => directTicket });

    render(<AdminCommunicationsPanel sessionId={SESSION_ID} heirs={baseHeirs} />);

    await waitFor(() => {
      expect(screen.getByTestId('executor-reply-textarea')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('executor-reply-textarea'), {
      target: { value: 'Please confirm your pickup window.' },
    });
    fireEvent.click(screen.getByTestId('send-executor-reply-btn'));

    await waitFor(() => {
      const directCall = global.fetch.mock.calls.find(
        ([url]) => url === `/api/sessions/${SESSION_ID}/help/direct`,
      );
      expect(directCall).toBeTruthy();
      expect(directCall[1]).toEqual(expect.objectContaining({ method: 'POST' }));
      expect(directCall[1].body).toBeInstanceOf(FormData);
      expect(directCall[1].body.get('heir_id')).toBe(HEIR_ID);
      expect(directCall[1].body.get('message')).toBe('Please confirm your pickup window.');
      expect(screen.getByText('Please confirm your pickup window.')).toBeInTheDocument();
    });
  });

  it('marks a ticket as resolved via the Mark Resolved button', async () => {
    const resolvedTicket = {
      ...openTicket,
      status: 'RESOLVED',
      resolved_at: '2026-06-16T12:10:00Z',
    };

    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => [openTicket] })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'resolved', ticket: resolvedTicket }),
      });

    render(<AdminCommunicationsPanel sessionId={SESSION_ID} heirs={baseHeirs} />);

    expect((await screen.findAllByText('Can you clarify who receives the clock?')).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText('Mark Resolved'));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/help/ticket-1/resolve',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('refreshes when a websocket support alert updates the store', async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
      .mockResolvedValueOnce({ ok: true, json: async () => [openTicket] });

    render(<AdminCommunicationsPanel sessionId={SESSION_ID} heirs={baseHeirs} />);

    // Initial state: no messages for this heir
    await waitFor(() => {
      expect(screen.getByTestId('executor-reply-textarea')).toBeInTheDocument();
    });

    // Simulate WebSocket alert → increments supportRefreshToken
    act(() => {
      useMediationStore.getState().recordSupportAlert({
        ticket_id: openTicket.id,
        heir_name: openTicket.legal_name,
        message: openTicket.message,
        timestamp: openTicket.created_at,
      });
    });

    expect((await screen.findAllByText('Can you clarify who receives the clock?')).length).toBeGreaterThan(0);
  });
});
