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
const AUDIO_FORMATS = [
  { mimeType: 'audio/mp4;codecs=mp4a.40.2', extension: 'm4a' },
  { mimeType: 'audio/mp4', extension: 'm4a' },
  { mimeType: 'audio/webm;codecs=opus', extension: 'webm' },
  { mimeType: 'audio/webm', extension: 'webm' },
  { mimeType: 'audio/ogg;codecs=opus', extension: 'ogg' },
];

function getRecordingFormat() {
  if (typeof MediaRecorder === 'undefined') return null;
  if (typeof MediaRecorder.isTypeSupported !== 'function') {
    return { mimeType: '', extension: 'webm' };
  }
  return AUDIO_FORMATS.find(({ mimeType }) => MediaRecorder.isTypeSupported(mimeType)) || null;
}

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

export default function AdminVoiceRecorder({ assetId, onSaved, onCleared }) {
  const [recordingState, setRecordingState] = useState('idle'); // idle | recording | recorded
  const [elapsed, setElapsed] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [playbackUrl, setPlaybackUrl] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [showMicSetup, setShowMicSetup] = useState(false);
  const [microphones, setMicrophones] = useState([]);
  const [selectedMicId, setSelectedMicId] = useState('');
  const [micSetupStatus, setMicSetupStatus] = useState('');
  const [testingMic, setTestingMic] = useState(false);

  const mediaRecorderRef = useRef(null);
  const setupStreamRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);
  const finalizeTimerRef = useRef(null);
  const playbackAudioRef = useRef(null);
  const playbackUrlRef = useRef(null);
  const blobRef = useRef(null);
  const recordingFormatRef = useRef(null);

  const secure = isSecureContext();

  const stopSetupStream = useCallback(() => {
    if (setupStreamRef.current) {
      setupStreamRef.current.getTracks().forEach((track) => track.stop());
      setupStreamRef.current = null;
    }
  }, []);

  const testMicrophone = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicSetupStatus('Microphone access is not available in this browser.');
      return;
    }

    setTestingMic(true);
    setMicSetupStatus('Requesting microphone access...');
    stopSetupStream();

    try {
      const audioConstraint = selectedMicId
        ? { deviceId: { exact: selectedMicId } }
        : true;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraint });
      setupStreamRef.current = stream;

      const devices = typeof navigator.mediaDevices.enumerateDevices === 'function'
        ? await navigator.mediaDevices.enumerateDevices()
        : [];
      const audioInputs = devices.filter((device) => device.kind === 'audioinput');
      setMicrophones(audioInputs);

      const activeTrack = stream.getAudioTracks?.()[0] || stream.getTracks()[0];
      const activeDeviceId = activeTrack?.getSettings?.().deviceId;
      if (!selectedMicId && activeDeviceId) {
        setSelectedMicId(activeDeviceId);
      } else if (!selectedMicId && audioInputs[0]?.deviceId) {
        setSelectedMicId(audioInputs[0].deviceId);
      }

      const deviceName = activeTrack?.label
        || audioInputs.find((device) => device.deviceId === activeDeviceId)?.label
        || 'Default microphone';
      setMicSetupStatus(`Connected to ${deviceName}. You can record now.`);
    } catch (err) {
      if (err?.name === 'NotAllowedError') {
        setMicSetupStatus('Microphone permission is blocked. Allow microphone access in Safari’s website settings, then try again.');
      } else if (err?.name === 'NotFoundError') {
        setMicSetupStatus('No microphone was found. Connect or enable a microphone, then try again.');
      } else if (err?.name === 'OverconstrainedError') {
        setSelectedMicId('');
        setMicSetupStatus('The selected microphone is no longer available. Choose another input and try again.');
      } else {
        setMicSetupStatus('Could not connect to the microphone. Try another input or reset the site permission.');
      }
    } finally {
      stopSetupStream();
      setTestingMic(false);
    }
  }, [selectedMicId, stopSetupStream]);

  // ── Start Recording ─────────────────────────────────────────────────
  const startRecording = useCallback(async () => {
    if (
      typeof MediaRecorder === 'undefined' ||
      !navigator.mediaDevices ||
      !navigator.mediaDevices.getUserMedia
    ) {
      setError('MediaRecorder is not supported in this browser.');
      return;
    }

    const recordingFormat = getRecordingFormat();
    if (!recordingFormat) {
      setError('This browser cannot record audio in a supported format.');
      return;
    }

    setError(null);
    chunksRef.current = [];

    try {
      stopSetupStream();
      const audioConstraint = selectedMicId
        ? { deviceId: { exact: selectedMicId } }
        : true;
      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraint });
      const recorder = recordingFormat.mimeType
        ? new MediaRecorder(stream, { mimeType: recordingFormat.mimeType })
        : new MediaRecorder(stream);
      recordingFormatRef.current = {
        mimeType: recorder.mimeType || recordingFormat.mimeType || 'audio/webm',
        extension: recordingFormat.extension,
      };

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        // Stop all tracks on the stream
        stream.getTracks().forEach((track) => track.stop());

        // Safari can deliver the final dataavailable event shortly after onstop.
        // Give that event time to arrive before deciding the recording is empty.
        finalizeTimerRef.current = setTimeout(() => {
          const blob = new Blob(chunksRef.current, {
            type: recordingFormatRef.current?.mimeType || 'audio/webm',
          });
          if (blob.size === 0) {
            blobRef.current = null;
            setPlaybackUrl(null);
            setRecordingState('idle');
            setError('No audio was captured. Check the selected microphone and try again.');
            setShowMicSetup(true);
            return;
          }
          blobRef.current = blob;

          if (playbackUrlRef.current) {
            URL.revokeObjectURL(playbackUrlRef.current);
          }
          const url = URL.createObjectURL(blob);
          playbackUrlRef.current = url;
          setPlaybackUrl(url);
          setRecordingState('recorded');
          if (assetId === 'staging' && onSaved) {
            onSaved(blob);
          }
          finalizeTimerRef.current = null;
        }, 300);
      };

      // Safari is more reliable when it emits one complete MP4/AAC recording
      // at stop instead of producing timesliced fragments.
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
        setShowMicSetup(true);
      } else if (err?.name === 'NotFoundError') {
        setError('No microphone was found. Open Microphone Setup to choose or reconnect one.');
        setShowMicSetup(true);
      } else if (err?.name === 'OverconstrainedError') {
        setSelectedMicId('');
        setError('The selected microphone is unavailable. Open Microphone Setup and choose another input.');
        setShowMicSetup(true);
      } else {
        setError('Failed to access microphone.');
        setShowMicSetup(true);
      }
    }
  }, [assetId, onSaved, selectedMicId, stopSetupStream]);

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
  const togglePlayback = useCallback(async () => {
    const audio = playbackAudioRef.current;
    if (!playbackUrl || !audio) return;

    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      setError(null);
      audio.currentTime = 0;
      try {
        await audio.play();
        setIsPlaying(true);
      } catch (err) {
        setIsPlaying(false);
        if (err?.name === 'NotAllowedError') {
          setError('Playback was blocked. Click Play again or allow audio for this site.');
        } else {
          setError('This recording could not be played. Re-do it and check the selected microphone.');
        }
      }
    }
  }, [playbackUrl, isPlaying]);

  // ── Re-do / Delete ──────────────────────────────────────────────────
  const resetRecording = useCallback(() => {
    if (finalizeTimerRef.current) {
      clearTimeout(finalizeTimerRef.current);
      finalizeTimerRef.current = null;
    }
    if (playbackUrl) {
      URL.revokeObjectURL(playbackUrl);
    }
    playbackUrlRef.current = null;
    if (playbackAudioRef.current) {
      playbackAudioRef.current.pause();
      playbackAudioRef.current = null;
    }
    setPlaybackUrl(null);
    blobRef.current = null;
    recordingFormatRef.current = null;
    chunksRef.current = [];
    setRecordingState('idle');
    setElapsed(0);
    setError(null);
    setIsPlaying(false);
    if (assetId === 'staging' && onCleared) {
      onCleared();
    }
  }, [assetId, onCleared, playbackUrl]);

  // ── Save / Upload ───────────────────────────────────────────────────
  const saveRecording = useCallback(async () => {
    if (!blobRef.current) {
      setError('No recording to save.');
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const extension = recordingFormatRef.current?.extension || 'webm';
      const formData = new FormData();
      formData.append('file', blobRef.current, `voice_story_${assetId}.${extension}`);

      const res = await fetch(`/api/assets/${assetId}/audio`, {
        method: 'POST',
        credentials: 'same-origin',
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
      if (finalizeTimerRef.current) clearTimeout(finalizeTimerRef.current);
      stopSetupStream();
      if (playbackUrlRef.current) URL.revokeObjectURL(playbackUrlRef.current);
      if (playbackAudioRef.current) {
        playbackAudioRef.current.pause();
        playbackAudioRef.current = null;
      }
    };
  }, [stopSetupStream]);

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
        <>
          <p className="text-sm" style={{ color: 'var(--color-primary)', marginBottom: 'var(--space-sm)' }}>
            ✅ Recording captured ({formatTime(elapsed)})
          </p>
          {assetId === 'staging' && (
            <p className="text-xs text-muted" style={{ marginBottom: 'var(--space-sm)' }}>
              Attached to this item automatically.
            </p>
          )}
          <audio
            ref={playbackAudioRef}
            src={playbackUrl || undefined}
            preload="metadata"
            onEnded={() => setIsPlaying(false)}
            onPause={() => setIsPlaying(false)}
            onError={() => {
              setIsPlaying(false);
              setError('This recording could not be played. Re-do it and check the selected microphone.');
            }}
          >
            Your browser does not support audio playback.
          </audio>
        </>
      )}

      {/* Error display */}
      {error && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <p className="text-sm" style={{ color: '#DC2626', marginBottom: '6px' }}>
            {error}
          </p>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setShowMicSetup(true)}
            data-testid={`open-mic-setup-${assetId}`}
          >
            🎙 Microphone Setup
          </button>
        </div>
      )}

      {showMicSetup && recordingState !== 'recording' && (
        <div
          style={{
            marginBottom: 'var(--space-md)',
            padding: 'var(--space-sm)',
            borderLeft: '3px solid var(--color-primary)',
            background: 'var(--color-card-bg)',
          }}
          data-testid={`mic-setup-${assetId}`}
        >
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 'var(--space-sm)',
            marginBottom: 'var(--space-sm)',
          }}>
            <strong className="text-sm">Microphone Setup</strong>
            <button
              type="button"
              className="btn-link"
              onClick={() => setShowMicSetup(false)}
              aria-label="Close microphone setup"
            >
              Close
            </button>
          </div>

          {microphones.length > 0 && (
            <div style={{ marginBottom: 'var(--space-sm)' }}>
              <label className="form-label text-xs" htmlFor={`microphone-select-${assetId}`}>
                Microphone
              </label>
              <select
                id={`microphone-select-${assetId}`}
                className="form-input"
                value={selectedMicId}
                onChange={(event) => {
                  setSelectedMicId(event.target.value);
                  setMicSetupStatus('');
                }}
                data-testid={`microphone-select-${assetId}`}
              >
                {microphones.map((device, index) => (
                  <option key={device.deviceId || index} value={device.deviceId}>
                    {device.label || `Microphone ${index + 1}`}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-sm)', alignItems: 'center' }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={testMicrophone}
              disabled={testingMic}
              data-testid={`test-microphone-${assetId}`}
            >
              {testingMic ? 'Connecting...' : 'Reconnect & Test'}
            </button>
            {selectedMicId && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  setSelectedMicId('');
                  setMicSetupStatus('System default selected. Choose Reconnect & Test.');
                }}
                disabled={testingMic}
                data-testid={`reset-microphone-${assetId}`}
              >
                Use System Default
              </button>
            )}
            <span className="text-xs text-muted">
              This re-requests access and refreshes the available inputs.
            </span>
          </div>

          {micSetupStatus && (
            <p
              className="text-sm"
              style={{
                margin: 'var(--space-sm) 0 0',
                color: micSetupStatus.startsWith('Connected')
                  ? 'var(--color-primary)'
                  : 'var(--color-text-muted)',
              }}
              role="status"
            >
              {micSetupStatus}
            </p>
          )}

          <p className="text-xs text-muted" style={{ margin: 'var(--space-sm) 0 0' }}>
            Safari: open Safari → Settings → Websites → Microphone, set localhost to Allow,
            then return here and choose Reconnect & Test.
          </p>
        </div>
      )}

      {/* Uploading state */}
      {uploading && (
        <p className="text-muted text-sm">Uploading audio story...</p>
      )}

      {/* Controls */}
      <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
        {recordingState === 'idle' && (
          <>
            <button
              className="btn btn-primary btn-sm"
              onClick={startRecording}
              disabled={!secure}
              data-testid={`record-btn-${assetId}`}
            >
              🔴 Record
            </button>
            {!showMicSetup && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setShowMicSetup(true)}
                data-testid={`setup-mic-btn-${assetId}`}
              >
                🎙 Setup Mic
              </button>
            )}
          </>
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
            {assetId !== 'staging' && (
              <button
                className="btn btn-primary btn-sm"
                onClick={saveRecording}
                disabled={uploading}
                data-testid={`save-recording-btn-${assetId}`}
              >
                💾 Save
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
