import React, { useState } from 'react';

function normalizeMediaSrc(src) {
  if (!src) return '';
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  return src.startsWith('/') ? src : `/${src}`;
}

/**
 * AssetGallery Component
 * Displays a single keepsake image or a premium visual carousel with prev/next arrows,
 * slide indicator dots, and a glassmorphic badge overlay displaying the angle label.
 */
export default function AssetGallery({
  images = [],
  title = 'Keepsake',
  onEditImage,
  imageActionLabel = 'Edit',
}) {
  const [activeIndex, setActiveIndex] = useState(0);
  const canEdit = typeof onEditImage === 'function';

  if (!images || images.length === 0) {
    return (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--color-bg)',
          color: 'var(--color-text-muted)',
          fontSize: '0.9rem',
          fontStyle: 'italic',
        }}
      >
        No Image Available
      </div>
    );
  }

  if (images.length === 1) {
    const img = images[0];
    return (
      <button
        type="button"
        onClick={() => canEdit && onEditImage(img)}
        disabled={!canEdit}
        aria-label={canEdit ? `${imageActionLabel} ${title || 'asset'} photo` : undefined}
        style={{
          width: '100%',
          height: '100%',
          position: 'relative',
          display: 'block',
          border: 'none',
          padding: 0,
          background: 'transparent',
          cursor: canEdit ? 'pointer' : 'default',
        }}
      >
        <img
          src={normalizeMediaSrc(img.image_uri)}
          alt={`${title} - ${img.angle_label || 'Primary'}`}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          loading="lazy"
        />
        {img.angle_label && img.angle_label !== 'Primary' && (
          <span
            style={{
              position: 'absolute',
              bottom: 8,
              left: 8,
              background: 'rgba(30, 41, 59, 0.7)',
              backdropFilter: 'blur(4px)',
              color: '#FFFFFF',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.7rem',
              fontWeight: 500,
            }}
          >
            {img.angle_label}
          </span>
        )}
      </button>
    );
  }

  const handlePrev = (e) => {
    e.stopPropagation();
    setActiveIndex((prev) => (prev === 0 ? images.length - 1 : prev - 1));
  };

  const handleNext = (e) => {
    e.stopPropagation();
    setActiveIndex((prev) => (prev === images.length - 1 ? 0 : prev + 1));
  };

  const activeImg = images[activeIndex];

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative', overflow: 'hidden' }}>
      {/* Active Image */}
      <button
        type="button"
        onClick={() => canEdit && onEditImage(activeImg)}
        disabled={!canEdit}
        aria-label={canEdit ? `${imageActionLabel} ${title || 'asset'} photo` : undefined}
        style={{
          width: '100%',
          height: '100%',
          display: 'block',
          border: 'none',
          padding: 0,
          background: 'transparent',
          cursor: canEdit ? 'pointer' : 'default',
        }}
      >
        <img
          src={normalizeMediaSrc(activeImg.image_uri)}
          alt={`${title} - ${activeImg.angle_label || `View ${activeIndex + 1}`}`}
          style={{ width: '100%', height: '100%', objectFit: 'cover', transition: 'all 0.3s ease-in-out' }}
          loading="lazy"
        />
      </button>

      {/* Angle Label Overlay */}
      {activeImg.angle_label && (
        <span
          style={{
            position: 'absolute',
            top: 8,
            left: 8,
            background: 'rgba(30, 41, 59, 0.75)',
            backdropFilter: 'blur(4px)',
            color: '#FFFFFF',
            padding: '4px 10px',
            borderRadius: '12px',
            fontSize: '0.75rem',
            fontWeight: 600,
            letterSpacing: '0.025em',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
          }}
        >
          {activeImg.angle_label}
        </span>
      )}

      {/* Navigation Arrows */}
      <button
        type="button"
        onClick={handlePrev}
        style={{
          position: 'absolute',
          left: 8,
          top: '50%',
          transform: 'translateY(-50%)',
          background: 'rgba(255, 255, 255, 0.85)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text)',
          width: 28,
          height: 28,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)',
          fontSize: '0.8rem',
          fontWeight: 'bold',
          transition: 'var(--transition-fast)',
          zIndex: 2,
        }}
        aria-label="Previous image"
      >
        ❮
      </button>
      <button
        type="button"
        onClick={handleNext}
        style={{
          position: 'absolute',
          right: 8,
          top: '50%',
          transform: 'translateY(-50%)',
          background: 'rgba(255, 255, 255, 0.85)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text)',
          width: 28,
          height: 28,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)',
          fontSize: '0.8rem',
          fontWeight: 'bold',
          transition: 'var(--transition-fast)',
          zIndex: 2,
        }}
        aria-label="Next image"
      >
        ❯
      </button>

      {/* Slide dots at bottom */}
      <div
        style={{
          position: 'absolute',
          bottom: 8,
          left: '50%',
          transform: 'translateX(-50%)',
          display: 'flex',
          gap: 6,
          zIndex: 2,
        }}
      >
        {images.map((_, idx) => (
          <button
            key={idx}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setActiveIndex(idx);
            }}
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: idx === activeIndex ? 'var(--color-primary)' : 'rgba(255, 255, 255, 0.6)',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
              transition: 'background 0.2s ease',
            }}
            aria-label={`Go to slide ${idx + 1}`}
          />
        ))}
      </div>
    </div>
  );
}
