import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useMediationStore } from '../store/useMediationStore';

const LEGAL_NOTICE = 'This system is strictly for personal property and keepsakes. Do not upload real estate, vehicles, or bank/financial accounts.';

const CATEGORIES = ['Jewelry', 'Furniture', 'Art', 'Other'];

const VALUATION_SOURCES = [
  'Professional Appraisal',
  'Tax Assessment',
  'Estate Sale Estimator',
  'Personal Estimate',
];

export default function AdminInventoryDashboard({ sessionId }) {
  const store = useMediationStore();
  const sessionStatus = useMediationStore((s) => s.sessionStatus);

  const [assets, setAssets] = useState([]);
  const [heirs, setHeirs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [editingAssetId, setEditingAssetId] = useState(null);

  // Edit form state
  const [editForm, setEditForm] = useState({
    title: '',
    description: '',
    category: 'Other',
    valuation_min: 0,
    valuation_max: 0,
    valuation_source: 'Personal Estimate',
    sentiment_tag: '',
  });

  // Pre-allocation state
  const [preAllocatingAssetId, setPreAllocatingAssetId] = useState(null);
  const [selectedHeirId, setSelectedHeirId] = useState('');

  // Audio upload state
  const [audioAssetId, setAudioAssetId] = useState(null);
  const [audioUploading, setAudioUploading] = useState(false);
  const audioInputRef = useRef(null);

  const isSetup = sessionStatus === 'SETUP';

  // ── Fetch assets and heirs ──────────────────────────────────────────────
  const fetchAssets = useCallback(async () => {
    if (!sessionId) return;
    try {
      setLoading(true);
      const res = await fetch(`/api/sessions/${sessionId}/assets`);
      if (res.ok) {
        const data = await res.json();
        setAssets(Array.isArray(data) ? data : data.assets || []);
      }
    } catch (err) {
      console.error('Failed to fetch assets', err);
      setError('Failed to load assets.');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  const fetchHeirs = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`/api/sessions/${sessionId}/heirs`);
      if (res.ok) {
        const data = await res.json();
        setHeirs(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to fetch heirs', err);
    }
  }, [sessionId]);

  useEffect(() => {
    fetchAssets();
    fetchHeirs();
  }, [fetchAssets, fetchHeirs]);

  // Poll for OCR status updates on PROCESSING assets
  useEffect(() => {
    const processingCount = assets.filter((a) => a.ocr_status === 'PROCESSING').length;
    if (processingCount === 0) return;

    const interval = setInterval(() => {
      fetchAssets();
    }, 3000);

    return () => clearInterval(interval);
  }, [assets, fetchAssets]);

  // ── File Upload / Stage ─────────────────────────────────────────────────
  async function handleFileUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      setError('Only image files are accepted.');
      return;
    }

    // 10MB limit
    if (file.size > 10 * 1024 * 1024) {
      setError('Image must be under 10MB.');
      return;
    }

    setError(null);
    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(`/api/sessions/${sessionId}/assets/stage`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Upload failed: ${res.status}`);
      }

      await fetchAssets();
      // eslint-disable-next-line no-undef
      e.target.value = ''; // Reset file input
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  // ── Edit Metadata ───────────────────────────────────────────────────────
  function startEditing(asset) {
    setEditingAssetId(asset.id);
    setEditForm({
      title: asset.title || '',
      description: asset.description || '',
      category: asset.category || 'Other',
      valuation_min: asset.valuation_min ?? 0,
      valuation_max: asset.valuation_max ?? 0,
      valuation_source: asset.valuation_source || 'Personal Estimate',
      sentiment_tag: asset.sentiment_tag || '',
    });
    setError(null);
  }

  function cancelEditing() {
    setEditingAssetId(null);
  }

  function handleEditFieldChange(field, value) {
    setEditForm((prev) => ({ ...prev, [field]: value }));
  }

  // ── Publish Asset ───────────────────────────────────────────────────────
  async function handlePublish(assetId) {
    setError(null);

    try {
      // If currently editing, use editForm; otherwise build from asset data
      const assetData =
        editingAssetId === assetId
          ? editForm
          : (() => {
              const asset = assets.find((a) => a.id === assetId);
              return {
                title: asset?.title || '',
                description: asset?.description || '',
                category: asset?.category || 'Other',
                valuation_min: asset?.valuation_min ?? 0,
                valuation_max: asset?.valuation_max ?? 0,
                valuation_source: asset?.valuation_source || 'Personal Estimate',
                sentiment_tag: asset?.sentiment_tag || '',
              };
            })();

      // Validate all fields are filled
      const missing = [];
      if (!assetData.title?.trim()) missing.push('title');
      if (!assetData.description?.trim()) missing.push('description');
      if (!assetData.category) missing.push('category');
      if (assetData.valuation_min == null || assetData.valuation_min < 0) missing.push('valuation_min');
      if (assetData.valuation_max == null || assetData.valuation_max < 0) missing.push('valuation_max');
      if (!assetData.valuation_source) missing.push('valuation source');

      if (missing.length > 0) {
        setError(`Cannot publish: missing required fields — ${missing.join(', ')}.`);
        return;
      }

      const res = await fetch(`/api/assets/${assetId}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(assetData),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Publish failed: ${res.status}`);
      }

      setEditingAssetId(null);
      await fetchAssets();
    } catch (err) {
      setError(err.message);
    }
  }

  // ── Delete Asset ────────────────────────────────────────────────────────
  async function handleDelete(assetId) {
    if (!window.confirm('Are you sure you want to permanently delete this asset and its associated image? This action cannot be undone.')) {
      return;
    }

    setError(null);
    try {
      const res = await fetch(`/api/assets/${assetId}`, { method: 'DELETE' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Delete failed: ${res.status}`);
      }
      await fetchAssets();
    } catch (err) {
      setError(err.message);
    }
  }

  // ── Pre-Allocation ──────────────────────────────────────────────────────
  function startPreAllocating(assetId) {
    setPreAllocatingAssetId(assetId);
    setSelectedHeirId('');
    setError(null);
  }

  function cancelPreAllocating() {
    setPreAllocatingAssetId(null);
    setSelectedHeirId('');
  }

  async function handlePreAllocate() {
    if (!selectedHeirId || !preAllocatingAssetId) return;

    setError(null);
    try {
      const res = await fetch(`/api/assets/${preAllocatingAssetId}/pre-allocate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ heir_id: selectedHeirId }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Pre-allocation failed: ${res.status}`);
      }

      setPreAllocatingAssetId(null);
      setSelectedHeirId('');
      await fetchAssets();
    } catch (err) {
      setError(err.message);
    }
  }

  // ── Audio Upload ────────────────────────────────────────────────────────
  function handleAudioSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    uploadAudio(audioAssetId, file);
    // eslint-disable-next-line no-undef
    e.target.value = '';
  }

  async function uploadAudio(assetId, file) {
    setError(null);
    setAudioUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(`/api/assets/${assetId}/audio`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Audio upload failed: ${res.status}`);
      }

      await fetchAssets();
      setAudioAssetId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setAudioUploading(false);
    }
  }

  async function handleDeleteAudio(assetId) {
    setError(null);
    try {
      const res = await fetch(`/api/assets/${assetId}/audio`, { method: 'DELETE' });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Audio deletion failed: ${res.status}`);
      }
      await fetchAssets();
    } catch (err) {
      setError(err.message);
    }
  }

  // ── Category badge color ────────────────────────────────────────────────
  function categoryBadgeStyle(category) {
    const colors = {
      Jewelry: '#C29F53',
      Furniture: '#8E7558',
      Art: '#7E6C84',
      Other: '#64748B',
    };
    return {
      display: 'inline-block',
      border: `1px solid ${colors[category] || colors.Other}`,
      color: colors[category] || colors.Other,
      padding: '2px 8px',
      borderRadius: '4px',
      fontSize: '0.75rem',
      fontWeight: 600,
      background: 'transparent',
    };
  }

  // ── Render ──────────────────────────────────────────────────────────────
  if (!isSetup) {
    return (
      <div className="archival-card" style={{ textAlign: 'center', padding: 'var(--space-xl)' }}>
        <h3 style={{ marginBottom: 'var(--space-md)' }}>Inventory Dashboard Locked</h3>
        <p className="text-muted">
          The inventory dashboard is only available during the Setup phase. Assets cannot be modified once the session is launched.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="archival-card" style={{ textAlign: 'center' }}>
        <p className="text-muted">Loading asset inventory...</p>
      </div>
    );
  }

  return (
    <div className="admin-inventory-dashboard" data-testid="admin-inventory-dashboard">
      {/* Error banner */}
      {error && (
        <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
          {error}
        </div>
      )}

      {/* Legal Notice */}
      <div
        className="asset-upload-scope-notice"
        data-testid="legal-scope-notice"
        style={{
          border: '1px solid var(--color-alert)',
          background: 'var(--color-alert-light)',
          padding: 'var(--space-md)',
          borderRadius: 'var(--radius-sm)',
          marginBottom: 'var(--space-md)',
          fontSize: '0.85rem',
          color: 'var(--color-text)',
          fontWeight: 500,
        }}
      >
        ⚠️ Scope Limit Notice: {LEGAL_NOTICE}
      </div>

      {/* Upload area */}
      <div className="archival-card" style={{ marginBottom: 'var(--space-lg)' }}>
        <h3 style={{ marginBottom: 'var(--space-sm)', fontFamily: 'var(--font-serif)' }}>
          Stage New Asset
        </h3>
        <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-md)' }}>
          Upload a photo of the item. Background OCR will identify details you can review and edit before publishing.
        </p>

        <div
          style={{
            border: '2px dashed var(--color-border)',
            borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-xl)',
            textAlign: 'center',
            cursor: 'pointer',
            position: 'relative',
          }}
          onClick={() => document.getElementById('asset-file-upload')?.click()}
        >
          {uploading ? (
            <p className="text-muted">Uploading — background OCR in progress...</p>
          ) : (
            <>
              <p style={{ marginBottom: 'var(--space-xs)', fontWeight: 600 }}>
                Click to upload or drag-and-drop an image
              </p>
              <p className="text-muted text-sm">JPEG, PNG, HEIC (max 10MB)</p>
            </>
          )}
          <input
            id="asset-file-upload"
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: 'none' }}
            onChange={handleFileUpload}
            data-testid="asset-file-input"
          />
        </div>
      </div>

      {/* Asset Grid */}
      {assets.length === 0 ? (
        <div className="archival-card" style={{ textAlign: 'center', padding: 'var(--space-xl)' }}>
          <h3 style={{ marginBottom: 'var(--space-sm)' }}>No Assets Staged</h3>
          <p className="text-muted">
            Upload photos of keepsakes, furniture, jewelry, and other personal property to begin building the estate catalog.
          </p>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
            gap: 'var(--space-md)',
          }}
        >
          {assets.map((asset) => {
            const isEditing = editingAssetId === asset.id;
            const isPreAllocating = preAllocatingAssetId === asset.id;

            return (
              <div
                key={asset.id}
                className="archival-card"
                data-testid={`asset-card-${asset.id}`}
                style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}
              >
                {/* Image */}
                {asset.image_uri && (
                  <div
                    style={{
                      aspectRatio: '4/3',
                      overflow: 'hidden',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--color-border)',
                      background: 'var(--color-bg)',
                    }}
                  >
                    <img
                      src={asset.image_uri}
                      alt={asset.title || 'Staged asset'}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                  </div>
                )}

                {/* OCR Status */}
                {asset.ocr_status === 'PROCESSING' && (
                  <p className="text-muted text-sm" data-testid={`ocr-processing-${asset.id}`}>
                    OCR extracting details...
                  </p>
                )}
                {asset.ocr_status === 'FAILED' && (
                  <p className="text-muted text-sm" style={{ color: 'var(--color-alert)' }}>
                    OCR could not identify details. Please enter them manually.
                  </p>
                )}

                {/* Status badge */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={categoryBadgeStyle(asset.category || 'Other')}>
                    {asset.category || 'Other'}
                  </span>
                  <span
                    className="text-sm"
                    style={{
                      padding: '2px 8px',
                      borderRadius: '4px',
                      background: asset.status === 'LIVE' ? 'var(--color-primary-light)' : 'var(--color-bg)',
                      color: asset.status === 'LIVE' ? 'var(--color-primary)' : 'var(--color-text-muted)',
                      fontWeight: 600,
                      fontSize: '0.7rem',
                      textTransform: 'uppercase',
                    }}
                  >
                    {asset.status || 'STAGED'}
                  </span>
                </div>

                {/* Edit form or display */}
                {isEditing ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                    <div>
                      <label className="form-label">Title</label>
                      <input
                        className="form-input"
                        value={editForm.title}
                        onChange={(e) => handleEditFieldChange('title', e.target.value)}
                        placeholder="Item title"
                        data-testid={`edit-title-${asset.id}`}
                      />
                    </div>
                    <div>
                      <label className="form-label">Description</label>
                      <textarea
                        className="form-input"
                        value={editForm.description}
                        onChange={(e) => handleEditFieldChange('description', e.target.value)}
                        rows={3}
                        placeholder="Describe the item..."
                        data-testid={`edit-description-${asset.id}`}
                      />
                    </div>
                    <div>
                      <label className="form-label">Category</label>
                      <select
                        className="form-input"
                        value={editForm.category}
                        onChange={(e) => handleEditFieldChange('category', e.target.value)}
                        data-testid={`edit-category-${asset.id}`}
                      >
                        {CATEGORIES.map((cat) => (
                          <option key={cat} value={cat}>{cat}</option>
                        ))}
                      </select>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-sm)' }}>
                      <div>
                        <label className="form-label">Min Value ($)</label>
                        <input
                          className="form-input"
                          type="number"
                          min={0}
                          value={editForm.valuation_min}
                          onChange={(e) => handleEditFieldChange('valuation_min', Number(e.target.value))}
                          data-testid={`edit-min-${asset.id}`}
                        />
                      </div>
                      <div>
                        <label className="form-label">Max Value ($)</label>
                        <input
                          className="form-input"
                          type="number"
                          min={0}
                          value={editForm.valuation_max}
                          onChange={(e) => handleEditFieldChange('valuation_max', Number(e.target.value))}
                          data-testid={`edit-max-${asset.id}`}
                        />
                      </div>
                    </div>
                    <div>
                      <label className="form-label">Valuation Source</label>
                      <select
                        className="form-input"
                        value={editForm.valuation_source}
                        onChange={(e) => handleEditFieldChange('valuation_source', e.target.value)}
                        data-testid={`edit-source-${asset.id}`}
                      >
                        {VALUATION_SOURCES.map((src) => (
                          <option key={src} value={src}>{src}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="form-label">Sentiment Tag</label>
                      <input
                        className="form-input"
                        value={editForm.sentiment_tag}
                        onChange={(e) => handleEditFieldChange('sentiment_tag', e.target.value)}
                        placeholder="e.g. Heirloom, Handmade..."
                        data-testid={`edit-sentiment-${asset.id}`}
                      />
                    </div>
                    <div style={{ display: 'flex', gap: 'var(--space-sm)', marginTop: 'var(--space-xs)' }}>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => handlePublish(asset.id)}
                        data-testid={`publish-btn-${asset.id}`}
                      >
                        Publish Live
                      </button>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={cancelEditing}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    {/* Display metadata */}
                    <div>
                      <h4 style={{ fontFamily: 'var(--font-serif)', marginBottom: '2px' }}>
                        {asset.title || 'Untitled Asset'}
                      </h4>
                      {asset.description && (
                        <p className="text-muted text-sm" style={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                        }}>
                          {asset.description}
                        </p>
                      )}
                      {asset.valuation_min != null && asset.valuation_max != null && (
                        <p className="text-sm" style={{ marginTop: '4px', color: 'var(--color-text)' }}>
                          ${asset.valuation_min.toLocaleString()} – ${asset.valuation_max.toLocaleString()}
                          {asset.valuation_source && (
                            <span className="text-muted"> · {asset.valuation_source}</span>
                          )}
                        </p>
                      )}
                      {asset.sentiment_tag && (
                        <span style={{
                          display: 'inline-block',
                          marginTop: '4px',
                          padding: '1px 6px',
                          borderRadius: '3px',
                          background: 'var(--color-bg)',
                          fontSize: '0.7rem',
                          fontStyle: 'italic',
                          color: 'var(--color-text-muted)',
                        }}>
                          {asset.sentiment_tag}
                        </span>
                      )}
                    </div>

                    {/* Pre-allocated indicator */}
                    {asset.status === 'PRE_ALLOCATED' && asset.pre_allocated_to_heir_name && (
                      <p className="text-sm" style={{ color: 'var(--color-primary)', fontWeight: 600 }}>
                        Pre-Allocated: {asset.pre_allocated_to_heir_name}
                      </p>
                    )}

                    {/* Audio indicator */}
                    {asset.audio_uri && (
                      <p className="text-sm" style={{ color: 'var(--color-primary)' }}>
                        🎙 Spoken Story Recorded
                      </p>
                    )}

                    {/* Pre-allocation dropdown */}
                    {isPreAllocating && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                        <label className="form-label">Assign to Heir (Specific Devise)</label>
                        <select
                          className="form-input"
                          value={selectedHeirId}
                          onChange={(e) => setSelectedHeirId(e.target.value)}
                          data-testid={`pre-allocate-select-${asset.id}`}
                        >
                          <option value="">Select heir...</option>
                          {heirs.map((heir) => (
                            <option key={heir.id} value={heir.id}>
                              {heir.username || `${heir.legal_first_name || ''} ${heir.legal_last_name || ''}`.trim() || heir.id}
                            </option>
                          ))}
                        </select>
                        <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={handlePreAllocate}
                            disabled={!selectedHeirId}
                            data-testid={`confirm-pre-allocate-${asset.id}`}
                          >
                            Confirm Pre-Allocation
                          </button>
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={cancelPreAllocating}
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Audio upload */}
                    {audioAssetId === asset.id && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}>
                        <label className="form-label">Upload Spoken Story (WebM/MP3/WAV, max 2 min)</label>
                        <input
                          type="file"
                          accept="audio/webm,audio/mp3,audio/wav,.webm,.mp3,.wav"
                          onChange={handleAudioSelect}
                          data-testid={`audio-file-input-${asset.id}`}
                        />
                        {audioUploading && <p className="text-muted text-sm">Uploading audio...</p>}
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => setAudioAssetId(null)}
                        >
                          Cancel Audio
                        </button>
                      </div>
                    )}

                    {/* Action buttons */}
                    <div style={{
                      display: 'flex',
                      gap: 'var(--space-sm)',
                      flexWrap: 'wrap',
                      marginTop: 'auto',
                      paddingTop: 'var(--space-sm)',
                      borderTop: '1px solid var(--color-border)',
                    }}>
                      {asset.status !== 'LIVE' && (
                        <>
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => startEditing(asset)}
                            data-testid={`edit-btn-${asset.id}`}
                          >
                            Edit & Publish
                          </button>
                          {asset.status !== 'PRE_ALLOCATED' && (
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => startPreAllocating(asset.id)}
                              data-testid={`pre-allocate-btn-${asset.id}`}
                            >
                              Pre-Allocate
                            </button>
                          )}
                        </>
                      )}
                      {asset.status !== 'LIVE' && (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => setAudioAssetId(asset.id)}
                          data-testid={`audio-btn-${asset.id}`}
                        >
                          {asset.audio_uri ? 'Replace Audio' : 'Add Voice Story'}
                        </button>
                      )}
                      {asset.audio_uri && (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleDeleteAudio(asset.id)}
                          style={{ color: 'var(--color-alert)' }}
                          data-testid={`delete-audio-btn-${asset.id}`}
                        >
                          Remove Audio
                        </button>
                      )}
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleDelete(asset.id)}
                        style={{ color: '#DC2626', marginLeft: 'auto' }}
                        data-testid={`delete-btn-${asset.id}`}
                      >
                        🗑 Delete
                      </button>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}