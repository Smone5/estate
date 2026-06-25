import React, { useState, useRef, useCallback } from 'react';
import { useMediationStore } from '../store/useMediationStore';

const API_BASE = '';
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

export default function IDScanner() {
  const userStatus = useMediationStore((s) => s.userStatus);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const fileInputRef = useRef(null);
  const streamRef = useRef(null);

  // Only render when userStatus is PROFILE_HOLD
  if (userStatus !== 'PROFILE_HOLD') return null;

  // ── Camera controls ──────────────────────────────────────────────────

  const openCamera = useCallback(async () => {
    setError(null);
    setSuccess(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      setCameraOpen(true);
    } catch (err) {
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setError('Camera access denied. Please grant camera permissions in your browser settings.');
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        setError('No camera found on this device. Please use the file upload option instead.');
      } else {
        setError('Unable to open camera. Please use the file upload option instead.');
      }
    }
  }, []);

  const closeCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    setCameraOpen(false);
  }, []);

  const capturePhoto = useCallback(() => {
    if (!videoRef.current || !canvasRef.current) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (blob) {
          uploadFile(blob, 'id-scan-camera.jpg');
          closeCamera();
        }
      },
      'image/jpeg',
      0.92,
    );
  }, [closeCamera]);

  // ── Upload logic ─────────────────────────────────────────────────────

  const uploadFile = useCallback(async (blobOrFile, filename) => {
    setUploading(true);
    setError(null);
    setSuccess(false);

    try {
      const formData = new FormData();
      const file = blobOrFile instanceof File
        ? blobOrFile
        : new File([blobOrFile], filename, { type: blobOrFile.type || 'image/jpeg' });
      formData.append('file', file);

      const res = await fetch(`${API_BASE}/api/heirs/me/upload-id`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Upload failed (${res.status})`);
      }

      setSuccess(true);
    } catch (err) {
      setError(err.message || 'Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  }, []);

  // ── File input / drag-and-drop ───────────────────────────────────────

  const handleFileChange = useCallback(
    (e) => {
      const file = e.target.files?.[0];
      if (file) {
        if (file.size > MAX_FILE_SIZE) {
          setError('File exceeds the 10MB size limit.');
          return;
        }
        uploadFile(file, file.name);
      }
    },
    [uploadFile],
  );

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      setDragOver(false);
      const file = e.dataTransfer?.files?.[0];
      if (file) {
        if (file.size > MAX_FILE_SIZE) {
          setError('File exceeds the 10MB size limit.');
          return;
        }
        uploadFile(file, file.name);
      }
    },
    [uploadFile],
  );

  const triggerFileInput = () => {
    fileInputRef.current?.click();
  };

  const handleEditProfile = useCallback(async () => {
    // Placeholder: edit profile action triggers the profile component
    // For now, alert that profile editing is available via settings
    // This will be wired to a modal or route in a future task
  }, []);

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <div style={{ marginBottom: 'var(--space-lg)' }}>
      <div className="archival-card" style={{ maxWidth: 640, margin: '0 auto' }}>
        <h2 style={{ marginBottom: 'var(--space-sm)' }}>Government ID Verification</h2>
        <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-md)' }}>
          Your identity must be verified by the Executor before you can participate in the
          mediation process. Please upload a photo or scan of your government-issued ID
          (Driver's License, Passport, or State ID).
        </p>

        <div
          className={`id-drop-zone ${dragOver ? 'id-drop-zone--active' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={!cameraOpen ? triggerFileInput : undefined}
          style={{
            border: `2px dashed ${dragOver ? 'var(--color-primary)' : 'var(--color-border)'}`,
            borderRadius: 4,
            padding: 'var(--space-2xl)',
            textAlign: 'center',
            cursor: cameraOpen ? 'default' : 'pointer',
            backgroundColor: dragOver ? 'var(--color-primary-light)' : 'transparent',
            transition: 'background-color 0.3s ease-in-out, border-color 0.3s ease-in-out',
            marginBottom: 'var(--space-md)',
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.pdf"
            onChange={handleFileChange}
            style={{ display: 'none' }}
            aria-label="Upload government ID scan"
          />

          {cameraOpen ? (
            <div style={{ position: 'relative', maxWidth: 400, margin: '0 auto' }}>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                style={{
                  width: '100%',
                  borderRadius: 4,
                  border: '1px solid var(--color-border)',
                }}
              />
              {/* Card-shaped overlay guide */}
              <div
                style={{
                  position: 'absolute',
                  top: '10%',
                  left: '8%',
                  width: '84%',
                  height: '80%',
                  border: '2px solid var(--color-primary)',
                  borderRadius: 4,
                  pointerEvents: 'none',
                  boxShadow: '0 0 0 9999px rgba(0,0,0,0.35)',
                }}
              />
              <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: 'var(--space-md)', justifyContent: 'center' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={capturePhoto}
                  disabled={uploading}
                >
                  {uploading ? 'Uploading...' : 'Capture ID'}
                </button>
                <button type="button" className="btn btn-secondary" onClick={closeCamera}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <div style={{ marginBottom: 'var(--space-md)' }}>
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--color-text)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.4 }}>
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              </div>
              <p className="text-muted" style={{ marginBottom: 'var(--space-sm)' }}>
                <strong>Drop ID Scan / Photo Here</strong>
              </p>
              <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-md)' }}>
                or click to browse files (JPG, PNG, PDF up to 10MB)
              </p>

              <div style={{ display: 'flex', gap: 'var(--space-md)', justifyContent: 'center' }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={(e) => {
                    e.stopPropagation();
                    openCamera();
                  }}
                >
                  Scan ID with Camera
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={(e) => {
                    e.stopPropagation();
                    triggerFileInput();
                  }}
                >
                  Choose File
                </button>
              </div>
            </>
          )}
        </div>

        {/* Status indicator */}
        <p
          className="text-sm"
          style={{
            fontStyle: 'italic',
            color: 'var(--color-text)',
            opacity: 0.7,
            marginBottom: 'var(--space-md)',
          }}
        >
          Your ID is encrypted locally with AES-256 and is permanently deleted as soon as
          your profile is verified by the Executor.
        </p>

        {/* Error display */}
        {error && (
          <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
            {error}
          </div>
        )}

        {/* Success display */}
        {success && (
          <div className="banner banner-success" style={{ marginBottom: 'var(--space-md)' }}>
            ID scan uploaded successfully. The Executor will review your submission shortly.
          </div>
        )}

        {/* Uploading indicator */}
        {uploading && !cameraOpen && (
          <div className="banner banner-info" style={{ marginBottom: 'var(--space-md)' }}>
            Uploading and encrypting your ID scan...
          </div>
        )}

        {/* Edit Profile button */}
        <div style={{ textAlign: 'right' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleEditProfile}
            style={{ fontSize: '0.813rem' }}
          >
            Edit Profile
          </button>
        </div>
      </div>

      {/* Hidden canvas for camera capture */}
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}