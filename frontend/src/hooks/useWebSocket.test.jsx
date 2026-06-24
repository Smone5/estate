// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWebSocket } from './useWebSocket';
import { useMediationStore } from '../store/useMediationStore';

class MockWebSocket {
  static OPEN = 1;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.OPEN;
    MockWebSocket.instances.push(this);
  }

  send = vi.fn();
  close = vi.fn();
}

MockWebSocket.instances = [];

describe('useWebSocket support communication frames', () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    global.WebSocket = MockWebSocket;
    useMediationStore.setState({
      session_id: 'session-123',
      heir_id: 'heir-123',
      supportRefreshToken: 0,
      openSupportRequests: [],
      latestSupportNotice: null,
      transientMessageQueue: [],
      networkStatus: 'Disconnected',
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('records support alerts and replies from websocket frames', () => {
    renderHook(() => useWebSocket());
    const ws = MockWebSocket.instances[0];

    act(() => {
      ws.onopen();
      ws.onmessage({
        data: JSON.stringify({
          type: 'support_alert',
          ticket_id: 'ticket-1',
          heir_name: 'Aaron Melton',
          message: 'I need help',
          timestamp: '2026-06-16T12:00:00Z',
        }),
      });
    });

    expect(useMediationStore.getState().openSupportRequests[0]).toMatchObject({
      ticket_id: 'ticket-1',
      heir_name: 'Aaron Melton',
    });
    expect(useMediationStore.getState().supportRefreshToken).toBe(1);

    act(() => {
      ws.onmessage({
        data: JSON.stringify({
          type: 'support_reply',
          ticket_id: 'ticket-1',
          message: 'I replied to your question.',
          responded_at: '2026-06-16T12:05:00Z',
        }),
      });
    });

    expect(useMediationStore.getState().latestSupportNotice).toMatchObject({
      type: 'reply',
      ticket_id: 'ticket-1',
      message: 'I replied to your question.',
    });
    expect(useMediationStore.getState().supportRefreshToken).toBe(2);
  });
});
