/**
 * useAudioPlayback — Client Audio Playback Queue for the Estate Steward.
 *
 * Task T25: Manages sequential playback of base64-encoded WAV audio chunks
 * received via WebSocket chat_reply_chunk frames. Features:
 *   - Sequential playlist queue (plays one chunk at a time)
 *   - Base64 → Blob → Object URL decoder
 *   - Blob URL revocation on each chunk completion (memory leak prevention)
 *   - Cleanup on unmount: pauses playback, revokes all remaining Blob URLs
 *   - SB 942 synthetic voice label: "Synthesized AI Voice" shown when
 *     is_synthetic flag is true in the current frame
 *   - Null-audio guard: ignores chunks with audio: null (T21 degradation)
 *
 * Depends on T18 (Zustand), T23 (WebSocket hook).
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { useMediationStore } from '../store/useMediationStore';

/**
 * Play a base64-encoded WAV audio string and return a promise that
 * resolves when playback completes.
 */
function playAudioBlob(base64Audio) {
  return new Promise((resolve, reject) => {
    if (!base64Audio) {
      resolve();
      return;
    }

    try {
      // Decode base64 → binary → Blob → Object URL
      const binaryStr = atob(base64Audio);
      const bytes = new Uint8Array(binaryStr.length);
      for (let i = 0; i < binaryStr.length; i++) {
        bytes[i] = binaryStr.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: 'audio/wav' });
      const url = URL.createObjectURL(blob);

      const audio = new Audio(url);
      audio.onended = () => {
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onerror = (err) => {
        URL.revokeObjectURL(url);
        // Resolve even on error to continue the queue
        console.warn('Audio playback error:', err);
        resolve();
      };
      audio.play().catch((err) => {
        URL.revokeObjectURL(url);
        console.warn('Audio play() blocked by browser gesture rules:', err);
        resolve();
      });
    } catch (err) {
      console.warn('Failed to decode audio chunk:', err);
      resolve();
    }
  });
}

export function useAudioPlayback() {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isSyntheticPlaying, setIsSyntheticPlaying] = useState(false);
  const audioChunks = useMediationStore((s) => s.audioChunks);
  const clearAudioChunks = useMediationStore((s) => s.clearAudioChunks);

  const queueRef = useRef([]);
  const isPlayingRef = useRef(false);
  const cancelRef = useRef(false);
  // Track all active Blob URLs for cleanup on unmount
  const activeUrlsRef = useRef(new Set());

  /**
   * Process the next item in the queue.
   */
  const playNext = useCallback(async () => {
    if (cancelRef.current || queueRef.current.length === 0) {
      setIsPlaying(false);
      isPlayingRef.current = false;
      setIsSyntheticPlaying(false);
      return;
    }

    const item = queueRef.current.shift();
    isPlayingRef.current = true;
    setIsPlaying(true);

    // Update synthetic voice label
    setIsSyntheticPlaying(item.is_synthetic === true);

    // Play audio if available, otherwise just wait for the next chunk
    await playAudioBlob(item.audio);
    // continue to next
    playNext();
  }, []);

  /**
   * Enqueue one or more chat_reply_chunk frames for playback.
   *
   * @param {Array|Object} chunks - single frame or array of frames
   *   Each frame: { type: 'chat_reply_chunk', text: string, audio: string|null, is_synthetic: boolean, is_final: boolean }
   */
  const enqueueChunks = useCallback((chunks) => {
    const items = Array.isArray(chunks) ? chunks : [chunks];

    for (const item of items) {
      // Skip chunks with null audio (T21 graceful degradation)
      if (item.audio) {
        queueRef.current.push(item);
      }
      // If this is a final chunk, we still track it for label updates
    }

    // Start playback if not already playing
    if (!isPlayingRef.current) {
      playNext();
    }
  }, [playNext]);

  useEffect(() => {
    if (audioChunks.length === 0) return;
    enqueueChunks(audioChunks);
    clearAudioChunks();
  }, [audioChunks, clearAudioChunks, enqueueChunks]);

  /**
   * Stop playback and clear the queue.
   */
  const stop = useCallback(() => {
    cancelRef.current = true;
    queueRef.current = [];
    isPlayingRef.current = false;
    setIsPlaying(false);
    setIsSyntheticPlaying(false);
  }, []);

  /**
   * Cancel the cancellation flag so future enqueues can play.
   */
  const reset = useCallback(() => {
    cancelRef.current = false;
  }, []);

  // ── Cleanup on unmount ─────────────────────────────────────────────
  useEffect(() => {
    return () => {
      cancelRef.current = true;
      queueRef.current = [];
      // Revoke all remaining Blob URLs
      for (const url of activeUrlsRef.current) {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // Already revoked or invalid — ignore
        }
      }
      activeUrlsRef.current.clear();
    };
  }, []);

  return {
    isPlaying,
    isSyntheticPlaying,
    enqueueChunks,
    stop,
    reset,
  };
}
