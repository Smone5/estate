import React, { useState } from 'react';
import Cropper from 'react-easy-crop';

const toRadians = (degrees) => (degrees * Math.PI) / 180;

function getRotatedSize(width, height, rotation) {
  const rotRad = toRadians(rotation);
  return {
    width: Math.abs(Math.cos(rotRad) * width) + Math.abs(Math.sin(rotRad) * height),
    height: Math.abs(Math.sin(rotRad) * width) + Math.abs(Math.cos(rotRad) * height),
  };
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    try {
      const url = new URL(src, window.location.href);
      if (url.origin !== window.location.origin) {
        image.crossOrigin = 'anonymous';
      }
    } catch { /* keep browser default */ }
    image.src = src;
  });
}

function normalizeImageSrc(src) {
  if (!src) return '';
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  return src.startsWith('/') ? src : `/${src}`;
}

async function renderEditedBlob(imageSrc, cropPixels, rotation, brightness, contrast) {
  const image = await loadImage(imageSrc);
  const safeCrop = cropPixels || {
    x: 0,
    y: 0,
    width: image.naturalWidth,
    height: image.naturalHeight,
  };

  const rotatedSize = getRotatedSize(image.naturalWidth, image.naturalHeight, rotation);
  const rotatedCanvas = document.createElement('canvas');
  const rotatedCtx = rotatedCanvas.getContext('2d');
  rotatedCanvas.width = rotatedSize.width;
  rotatedCanvas.height = rotatedSize.height;

  rotatedCtx.translate(rotatedSize.width / 2, rotatedSize.height / 2);
  rotatedCtx.rotate(toRadians(rotation));
  rotatedCtx.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);

  const outputCanvas = document.createElement('canvas');
  const outputCtx = outputCanvas.getContext('2d');
  outputCanvas.width = Math.max(1, Math.round(safeCrop.width));
  outputCanvas.height = Math.max(1, Math.round(safeCrop.height));
  outputCtx.filter = `brightness(${brightness}%) contrast(${contrast}%)`;
  outputCtx.drawImage(
    rotatedCanvas,
    safeCrop.x,
    safeCrop.y,
    safeCrop.width,
    safeCrop.height,
    0,
    0,
    outputCanvas.width,
    outputCanvas.height,
  );

  return new Promise((resolve, reject) => {
    outputCanvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error('Could not export edited image.'));
      },
      'image/webp',
      0.9,
    );
  });
}

export default function ImageEditModal({ image, title, onCancel, onSave, saving = false }) {
  const imageSrc = normalizeImageSrc(image.image_uri);
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [brightness, setBrightness] = useState(100);
  const [contrast, setContrast] = useState(100);
  const [cropPixels, setCropPixels] = useState(null);
  const [error, setError] = useState(null);

  async function handleSave() {
    setError(null);
    try {
      const blob = await renderEditedBlob(imageSrc, cropPixels, rotation, brightness, contrast);
      await onSave(blob);
    } catch (err) {
      setError(err.message || 'Image edit failed.');
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Edit photo"
      className="drawer-overlay"
      onClick={onCancel}
    >
      <div
        className="drawer-content"
        style={{ maxWidth: 920, width: '95vw' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-header">
          <h3>Edit Photo</h3>
          <button type="button" className="close-btn" onClick={onCancel} aria-label="Close editor">
            x
          </button>
        </div>

        <div className="drawer-body" style={{ gap: 'var(--space-md)' }}>
          <div
            style={{
              height: 'min(58vh, 540px)',
              minHeight: 320,
              position: 'relative',
              background: '#111827',
              borderRadius: 'var(--radius-sm)',
              overflow: 'hidden',
            }}
          >
            <Cropper
              image={imageSrc}
              crop={crop}
              zoom={zoom}
              rotation={rotation}
              aspect={4 / 3}
              onCropChange={setCrop}
              onZoomChange={setZoom}
              onRotationChange={setRotation}
              onCropComplete={(_, pixels) => setCropPixels(pixels)}
              mediaProps={{ alt: title || image.angle_label || 'Asset photo' }}
              style={{ mediaStyle: { filter: `brightness(${brightness}%) contrast(${contrast}%)` } }}
            />
          </div>

          {error && <div className="banner banner-error">{error}</div>}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 'var(--space-md)' }}>
            <label className="form-label">
              Zoom
              <input
                type="range"
                min="1"
                max="3"
                step="0.05"
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
                style={{ width: '100%' }}
              />
            </label>
            <label className="form-label">
              Brightness
              <input
                type="range"
                min="50"
                max="150"
                step="1"
                value={brightness}
                onChange={(e) => setBrightness(Number(e.target.value))}
                style={{ width: '100%' }}
              />
            </label>
            <label className="form-label">
              Contrast
              <input
                type="range"
                min="50"
                max="150"
                step="1"
                value={contrast}
                onChange={(e) => setContrast(Number(e.target.value))}
                style={{ width: '100%' }}
              />
            </label>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 'var(--space-xs)' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setRotation((value) => value - 90)}
              >
                Rotate Left
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setRotation((value) => value + 90)}
              >
                Rotate Right
              </button>
            </div>
          </div>
        </div>

        <div className="drawer-footer">
          <button type="button" className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Edited Photo'}
          </button>
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
