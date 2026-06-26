/**
 * useWebSocket — Client WebSocket connection hook for the Estate Steward.
 *
 * Tasks T23, T24, T25: Establishes a persistent per-session WebSocket,
 * handles reconnect backoffs, offline message queue buffering, and
 * dispatches incoming chat_reply_chunk / session_status frames to
 * the Zustand store.
 *
 * Depends on:
 *   - useMediationStore (for session_id, heir_id, queue, networkStatus)
 *   - T22  (/api/sessions/{session_id}/ws server endpoint)
 *   - T18  (Zustand store with transientMessageQueue)
 *
 * Per Frontend Spec §5.1–5.3:
 *   - Connects to ws://<host>/api/sessions/{session_id}/ws
 *   - Exponential backoff reconnect (1s → 2s → 4s → 8s → 16s, max 5)
 *   - All messages typed while offline are appended to queue and flushed
 *     inside the WebSocket onopen handler
 *   - Incoming chat_reply_chunk frames are parsed; audio: null handled
 *   - session_status frames update store state
 */

import { useEffect, useRef, useCallback } from 'react';
import { useMediationStore } from '../store/useMediationStore';

const MAX_RECONNECT_ATTEMPTS = 5;
const INITIAL_RECONNECT_DELAY_MS = 1000;

/**
 * Determine the WebSocket URL from the current page location.
 * Uses wss:// in production (HTTPS), ws:// in development (localhost).
 */
function buildWsUrl(sessionId) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return `${protocol}//${host}/api/sessions/${encodeURIComponent(sessionId)}/ws`;
}

/**
 * useWebSocket hook
 *
 * Usage:
 *   const { send, isConnected } = useWebSocket();
 *
 * @returns {{ send: (payload: object) => void, isConnected: () => boolean }}
 */
export function useWebSocket() {
  const wsRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef(null);
  const mountedRef = useRef(true);

  const sessionId = useMediationStore((s) => s.session_id);
  const addMessage = useMediationStore((s) => s.addMessage);
  const enqueueAudioChunk = useMediationStore((s) => s.enqueueAudioChunk);
  const setNetworkStatus = useMediationStore((s) => s.setNetworkStatus);
  const flushOfflineQueue = useMediationStore((s) => s.flushOfflineQueue);
  const enqueueOfflineMessage = useMediationStore((s) => s.enqueueOfflineMessage);
  const setSession = useMediationStore((s) => s.setSession);
  const recordSupportAlert = useMediationStore((s) => s.recordSupportAlert);
  const recordSupportReply = useMediationStore((s) => s.recordSupportReply);

  /**
   * Close the current WebSocket connection cleanly.
   */
  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onmessage = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  /**
   * Connect (or reconnect) the WebSocket.
   */
  const connect = useCallback(() => {
    if (!sessionId || !mountedRef.current) return;

    disconnect();

    // Don't exceed max reconnect attempts
    if (reconnectAttemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      setNetworkStatus('Disconnected');
      return;
    }

    setNetworkStatus('Connecting...');

    const url = buildWsUrl(sessionId);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close();
        return;
      }
      reconnectAttemptsRef.current = 0;
      setNetworkStatus('Connected');

      // Flush any messages queued while offline
      const store = useMediationStore.getState();
      if (store.transientMessageQueue.length > 0) {
        store.flushOfflineQueue((msg) => {
          if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(msg));
          }
        });
      }
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;
      try {
        const frame = JSON.parse(event.data);

        switch (frame.type) {
          case 'chat_reply_chunk': {
            // Per Compliance Spec §2.5: all frames carry is_synthetic.
            // audio may be null (T21 graceful degradation).
            const text = frame.text || '';
            if (text) {
              addMessage({ sender: 'agent', text });
            }
            enqueueAudioChunk(frame);
            if (frame.is_final && text) {
              // Mark final chunk — nothing extra to do; audio queue
              // in T25 will detect the final chunk
            }
            break;
          }
          case 'session_status': {
            setSession({
              status: frame.status,
              is_paused: frame.is_paused || false,
              is_deadlocked: frame.is_deadlocked || false,
              is_hitl_suspended: frame.is_hitl_suspended || false,
            });
            break;
          }
          case 'announcement_updated': {
            const store = useMediationStore.getState();
            store.setSession({
              ...store,
              announcement: frame.announcement ?? null,
              announcement_updated_at: frame.announcement_updated_at ?? null,
            });
            break;
          }
          case 'support_alert': {
            recordSupportAlert({
              ticket_id: frame.ticket_id,
              heir_name: frame.heir_name,
              message: frame.message,
              timestamp: frame.timestamp,
            });
            break;
          }
          case 'support_reply': {
            recordSupportReply({
              type: 'reply',
              ticket_id: frame.ticket_id,
              message: frame.message,
              timestamp: frame.responded_at || frame.timestamp,
            });
            break;
          }
          case 'error': {
            // Log server errors without crashing the UI
            console.warn(
              'WebSocket server error:',
              frame.message || 'Unknown error',
            );
            break;
          }
          case 'pong': {
            // Ping/pong heartbeat — no action needed
            break;
          }
          default:
            // Unknown frame type — log and ignore
            if (frame.type) {
              console.debug('WebSocket frame:', frame.type, frame);
            }
        }
      } catch (err) {
        console.warn('Failed to parse WebSocket message:', event.data, err);
      }
    };

    ws.onclose = (event) => {
      if (!mountedRef.current) return;

      wsRef.current = null;

      // Normal closure (e.g., server shutdown) — don't reconnect
      if (event.code === 1000 || event.code === 1001) {
        setNetworkStatus('Disconnected');
        return;
      }

      // Abnormal closure — schedule reconnect with backoff
      if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
        const delay =
          INITIAL_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttemptsRef.current);
        setNetworkStatus('Reconnecting...');

        reconnectTimerRef.current = setTimeout(() => {
          reconnectAttemptsRef.current += 1;
          connect();
        }, delay);
      } else {
        setNetworkStatus('Disconnected');
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror — let onclose handle reconnect
      // Just ensure network status reflects the issue
      if (mountedRef.current) {
        setNetworkStatus('Reconnecting...');
      }
    };
  }, [sessionId, disconnect, setNetworkStatus, flushOfflineQueue, addMessage, enqueueAudioChunk, setSession, recordSupportAlert, recordSupportReply]);

  /**
   * Send a JSON payload over the WebSocket.
   * If offline, enqueue for later delivery.
   */
  const send = useCallback(
    (payload) => {
      const store = useMediationStore.getState();
      if (
        wsRef.current &&
        wsRef.current.readyState === WebSocket.OPEN
      ) {
        wsRef.current.send(JSON.stringify(payload));
      } else {
        // Offline — buffer the message
        enqueueOfflineMessage(payload);
      }
    },
    [enqueueOfflineMessage],
  );

  /**
   * Check whether the WebSocket is currently connected.
   */
  const isConnected = useCallback(
    () =>
      wsRef.current !== null &&
      wsRef.current.readyState === WebSocket.OPEN,
    [],
  );

  // ── Lifecycle ─────────────────────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true;

    if (sessionId) {
      connect();
    }

    return () => {
      mountedRef.current = false;
      disconnect();
    };
  }, [sessionId, connect, disconnect]);

  return { send, isConnected };
}
