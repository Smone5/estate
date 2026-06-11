/**
 * AdminVoiceRecorder — MediaRecorder-based voice story recording widget.
 *
 * Task T45: Built into the Admin asset staging card. Features:
 *   - Record/Stop controls with MediaRecorder API
 *   - Pulsing red ring + elapsed timer display during recording (max 2:00)
 *   - Playback controls (listen to recorded audio)
 *   - Re-do / Delete button to reset
 *   - Save trigger fires upload to POST /api/assets/{assetId}/audio
 *   - HTTPS guard: disables Record button over insecure HTTP
 *   - Aesthetics: housed in a "Record Spoken Story / Provenance" panel
 *     with Sage-Green border and var(--color-primary-light) background
 *
 * Props:
 *   - assetId: string — the asset to upload audio for
 *   - onSaved: () => void — callback after successful upload
 */

import React, { useState, useRef, useCallback } from 'react';

const MAX_DURATION_SEC = 120; // 2 minutes
const MIME_TYPE = 'audio/webm';

function isSecureContext() {
  const protocol = window.location.protocol;
  if (protocol === 'https:') return true;
  const hostname = window.location.hostname;
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

function formatTime(totalSeconds) {
  const mins = Math.floor(totalSeconds / 60);
  const secs = Math.floor(totalSeconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export default function AdminVoiceRecorder({ assetId, onSaved }) {
  const [recordingState, setRecordingState] = useState('idle'); // idle | recording | recorded
  const [elapsed, setElapsed] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [playbackUrl, setPlaybackUrl] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);

  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const playbackAudioRef = useRef(null);
  const blobRef = useRef(null);

  const secure = isSecureContext();

  // ── Start Recording ─────────────────────────────────────────────────
  const startRecording = useCallback(async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setError('MediaRecorder is not supported in this browser.');
      return;
    }

    setError(null);
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: MIME_TYPE });

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        // Stop all tracks on the stream
        stream.getTracks().forEach((track) => track.stop());

        // Build blob from accumulated chunks
        const blob = new Blob(chunksRef.current, { type: MIME_TYPE });
        blobRef.current = blob;

        // Create playback URL
        if (playbackUrl) {
          URL.revokeObjectURL(playbackUrl);
        }
        const url = URL.createObjectURL(blob);
        setPlaybackUrl(url);
        setRecordingState('recorded');
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setRecordingState('recording');
      setElapsed(0);

      // Start timer
      timerRef.current = setInterval(() => {
        setElapsed((prev) => {
          const next = prev + 1;
          if (next >= MAX_DURATION_SEC) {
            // Auto-stop at limit
            if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
              mediaRecorderRef.current.stop();
            }
            return MAX_DURATION_SEC;
          }
          return next;
        });
      }, 1000);
    } catch (err) {
      if (err?.name === 'NotAllowedError') {
        setError('Microphone access denied. Please enable microphone permissions.');
      } else {
        setError('Failed to access microphone.');
      }
    }
  }, [playbackUrl]);

  // ── Stop Recording ──────────────────────────────────────────────────
  const stopRecording = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  // ── Play / Pause Playback ───────────────────────────────────────────
  const togglePlayback = useCallback(() => {
    if (!playbackUrl) return;

    if (!playbackAudioRef.current) {
      const audio = new Audio(playbackUrl);
      audio.onended = () => setIsPlaying(false);
      audio.onerror = () => {
        setIsPlaying(false);
        setError('Failed to play recording.');
      };
      playbackAudioRef.current = audio;
    }

    if (isPlaying) {
      playbackAudioRef.current.pause();
      setIsPlaying(false);
    } else {
      playbackAudioRef.current.currentTime = 0;
      playbackAudioRef.current.play().catch(() => {
        setError('Playback blocked by browser.');
      });
      setIsPlaying(true);
    }
  }, [playbackUrl, isPlaying]);

  // ── Re-do / Delete ──────────────────────────────────────────────────
  const resetRecording = useCallback(() => {
    if (playbackUrl) {
      URL.revokeObjectURL(playbackUrl);
    }
    if (playbackAudioRef.current) {
      playbackAudioRef.current.pause();
      playbackAudioRef.current = null;
    }
    setPlaybackUrl(null);
    blobRef.current = null;
    chunksRef.current = [];
    setRecordingState('idle');
    setElapsed(0);
    setError(null);
    setIsPlaying(false);
  }, [playbackUrl]);

  // ── Save / Upload ───────────────────────────────────────────────────
  const saveRecording = useCallback(async () => {
    if (!blobRef.current) {
      setError('No recording to save.');
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', blobRef.current, `voice_story_${assetId}.webm`);

      const res = await fetch(`/api/assets/${assetId}/audio`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Upload failed (${res.status})`);
      }

      // Clean up
      resetRecording();
      if (onSaved) onSaved();
    } catch (err) {
      setError(err.message || 'Failed to upload audio story.');
    } finally {
      setUploading(false);
    }
  }, [assetId, onSaved, resetRecording]);

  // ── Cleanup on unmount ──────────────────────────────────────────────
  React.useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (playbackUrl) URL.revokeObjectURL(playbackUrl);
      if (playbackAudioRef.current) {
        playbackAudioRef.current.pause();
        playbackAudioRef.current = null;
      }
    };
  }, [playbackUrl]);

  // ── Render ──────────────────────────────────────────────────────────
  if (!secure) {
    return (
      <div
        data-testid={`voice-recorder-${assetId}`}
        style={{
          border: '2px solid var(--color-primary-light)',
          background: 'rgba(132, 155, 115, 0.08)',
          borderRadius: '6px',
          padding: 'var(--space-md)',
          marginTop: 'var(--space-sm)',
        }}
      >
        <h5 style={{
          fontFamily: 'var(--font-serif)',
          margin: '0 0 var(--space-sm) 0',
          fontSize: '0.85rem',
          color: 'var(--color-primary)',
        }}>
          Record Spoken Story / Provenance
        </h5>
        <p className="text-muted text-sm">
          Voice recording requires a secure HTTPS connection.
        </p>
      </div>
    );
  }

  return (
    <div
      data-testid={`voice-recorder-${assetId}`}
      style={{
        border: '2px solid var(--color-primary-light)',
        background: 'rgba(132, 155, 115, 0.08)',
        borderRadius: '6px',
        padding: 'var(--space-md)',
        marginTop: 'var(--space-sm)',
      }}
    >
      <h5 style={{
        fontFamily: 'var(--font-serif)',
        margin: '0 0 var(--space-sm) 0',
        fontSize: '0.85rem',
        color: 'var(--color-primary)',
      }}>
        Record Spoken Story / Provenance
      </h5>

      {/* Timer display */}
      {recordingState === 'recording' && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-sm)',
          marginBottom: 'var(--space-sm)',
        }}>
          <span style={{
            display: 'inline-block',
            width: '12px',
            height: '12px',
            borderRadius: '50%',
            background: '#DC2626',
            animation: 'pulse 1s infinite',
          }} />
          <span style={{
            fontFamily: 'monospace',
            fontSize: '0.85rem',
            color: 'var(--color-text)',
            fontWeight: 600,
          }}>
            {formatTime(elapsed)} / {formatTime(MAX_DURATION_SEC)}
          </span>
        </div>
      )}

      {recordingState === 'recorded' && (
        <p className="text-sm" style={{ color: 'var(--color-primary)', marginBottom: 'var(--space-sm)' }}>
          ✅ Recording captured ({formatTime(elapsed)})
        </p>
      )}

      {/* Error display */}
      {error && (
        <p className="text-sm" style={{ color: '#DC2626', marginBottom: 'var(--space-sm)' }}>
          {error}
        </p>
      )}

      {/* Uploading state */}
      {uploading && (
        <p className="text-muted text-sm">Uploading audio story...</p>
      )}

      {/* Controls */}
      <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
        {recordingState === 'idle' && (
          <button
            className="btn btn-primary btn-sm"
            onClick={startRecording}
            disabled={!secure}
            data-testid={`record-btn-${assetId}`}
          >
            🔴 Record
          </button>
        )}

        {recordingState === 'recording' && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={stopRecording}
            data-testid={`stop-btn-${assetId}`}
          >
            ⏹ Stop
          </button>
        )}

        {recordingState === 'recorded' && (
          <>
            <button
              className="btn btn-primary btn-sm"
              onClick={togglePlayback}
              data-testid={`play-btn-${assetId}`}
            >
              {isPlaying ? '⏸ Pause' : '▶ Play'}
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={resetRecording}
              data-testid={`redo-btn-${assetId}`}
            >
              🔄 Re-do
            </button>
            <button
              className="btn btn-primary btn-sm"
              onClick={saveRecording}
              disabled={uploading}
              data-testid={`save-recording-btn-${assetId}`}
            >
              💾 Save
            </button>
          </>
        )}
      </div>
    </div>
  );
}