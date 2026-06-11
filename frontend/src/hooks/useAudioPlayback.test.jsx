// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAudioPlayback } from './useAudioPlayback';
import { useMediationStore } from '../store/useMediationStore';

describe('useAudioPlayback compliance queue', () => {
  let audioInstances;

  beforeEach(() => {
    audioInstances = [];
    useMediationStore.setState({ audioChunks: [] });

    global.URL.createObjectURL = vi.fn(() => 'blob:test-audio');
    global.URL.revokeObjectURL = vi.fn();

    global.Audio = vi.fn().mockImplementation((url) => {
      const audio = {
        url,
        onended: null,
        onerror: null,
        play: vi.fn().mockResolvedValue(undefined),
        pause: vi.fn(),
      };
      audioInstances.push(audio);
      return audio;
    });
  });

  it('propagates SB 942 is_synthetic from queued websocket chunks into playback state', async () => {
    const { result } = renderHook(() => useAudioPlayback());

    act(() => {
      useMediationStore.getState().enqueueAudioChunk({
        type: 'chat_reply_chunk',
        text: 'This is a synthesized response.',
        audio: btoa('wav-bytes'),
        is_synthetic: true,
        is_final: true,
      });
    });

    await waitFor(() => {
      expect(result.current.isPlaying).toBe(true);
      expect(result.current.isSyntheticPlaying).toBe(true);
    });

    expect(audioInstances).toHaveLength(1);
    expect(useMediationStore.getState().audioChunks).toEqual([]);

    await act(async () => {
      audioInstances[0].onended();
    });

    await waitFor(() => {
      expect(result.current.isPlaying).toBe(false);
      expect(result.current.isSyntheticPlaying).toBe(false);
    });
  });

  it('ignores null audio chunks without raising playback state', async () => {
    const { result } = renderHook(() => useAudioPlayback());

    act(() => {
      useMediationStore.getState().enqueueAudioChunk({
        type: 'chat_reply_chunk',
        text: 'Text-only fallback.',
        audio: null,
        is_synthetic: true,
        is_final: true,
      });
    });

    await waitFor(() => {
      expect(useMediationStore.getState().audioChunks).toEqual([]);
    });

    expect(audioInstances).toHaveLength(0);
    expect(result.current.isPlaying).toBe(false);
    expect(result.current.isSyntheticPlaying).toBe(false);
  });
});
