import React, { useState, useEffect } from 'react';

export default function ForceAllocationConsole({ sessionId, onOverrideComplete }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const [heirs, setHeirs] = useState([]);
  const [assets, setAssets] = useState([]);
  const [heirValuations, setHeirValuations] = useState({}); // heir_id -> [valuations]
  
  // State for overrides: asset_id -> { allocated_to_id, reason }
  const [overrides, setOverrides] = useState({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;

    async function fetchData() {
      try {
        setLoading(true);
        setError(null);

        // 1. Fetch heirs
        const heirsRes = await fetch(`/api/sessions/${sessionId}/heirs`);
        if (!heirsRes.ok) throw new Error(`Failed to load heirs: ${heirsRes.status}`);
        const heirsData = await heirsRes.json();

        // 2. Fetch assets
        const assetsRes = await fetch(`/api/sessions/${sessionId}/assets`);
        if (!assetsRes.ok) throw new Error(`Failed to load assets: ${assetsRes.status}`);
        const assetsData = await assetsRes.json();

        if (cancelled) return;
        setHeirs(heirsData);
        setAssets(assetsData);

        // 3. Fetch valuations for each heir
        const valuationsMap = {};
        for (const heir of heirsData) {
          try {
            const valRes = await fetch(`/api/sessions/${sessionId}/heirs/${heir.id}/valuations`);
            if (valRes.ok) {
              const valData = await valRes.json();
              valuationsMap[heir.id] = valData;
            }
          } catch (e) {
            console.error(`Could not load valuations for heir ${heir.username}`, e);
          }
        }

        if (cancelled) return;
        setHeirValuations(valuationsMap);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => { cancelled = true; };
  }, [sessionId]);

  // Identify contested/deadlocked assets
  // Contested assets are LIVE assets (status === 'LIVE')
  const contestedAssets = assets.filter((a) => a.status === 'LIVE');

  // Helper to get all bids placed on a specific asset
  const getBidsForAsset = (assetId) => {
    const bids = [];
    heirs.forEach((heir) => {
      const vals = heirValuations[heir.id] || [];
      const val = vals.find((v) => v.asset_id === assetId);
      if (val && val.points > 0) {
        bids.push({
          heirId: heir.id,
          username: heir.username,
          points: val.points,
          reasoning: val.reasoning,
          isReasoningShared: val.is_reasoning_shared,
        });
      }
    });
    // Sort descending by points
    return bids.sort((a, b) => b.points - a.points);
  };

  const handleSelectionChange = (assetId, heirId) => {
    setOverrides((prev) => ({
      ...prev,
      [assetId]: {
        ...prev[assetId],
        allocated_to_id: heirId,
      },
    }));
  };

  const handleReasonChange = (assetId, reasonText) => {
    setOverrides((prev) => ({
      ...prev,
      [assetId]: {
        ...prev[assetId],
        reason: reasonText,
      },
    }));
  };

  const isFormValid = () => {
    // Need at least one override set up
    const overrideItems = Object.entries(overrides).filter(
      ([_, val]) => val && val.allocated_to_id
    );
    if (overrideItems.length === 0) return false;

    // All set overrides must have a valid reason (min 5, max 250 chars)
    return overrideItems.every(([_, val]) => {
      const reason = val.reason || '';
      return reason.length >= 5 && reason.length <= 250;
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isFormValid() || submitting) return;

    setSubmitting(true);
    setError(null);
    setSuccess(null);

    // Build List[AdminOverrideRequest] body payload
    const payload = Object.entries(overrides)
      .filter(([_, val]) => val && val.allocated_to_id)
      .map(([assetId, val]) => ({
        asset_id: assetId,
        allocated_to_id: val.allocated_to_id,
        reason: val.reason,
      }));

    try {
      const res = await fetch(`/api/sessions/${sessionId}/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Override submission failed (${res.status})`);
      }

      setSuccess('Fiduciary overrides successfully applied. Deadlock resolved.');
      setOverrides({});
      if (onOverrideComplete) {
        onOverrideComplete();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="archival-card text-center" style={{ width: '100%' }}>
        <h3 style={{ marginBottom: 'var(--space-md)' }}>Loading Force Allocation Console</h3>
        <p className="text-muted">Fetching session catalog, heir rosters, and submitted valuations...</p>
      </div>
    );
  }

  return (
    <div className="force-allocation-console" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-lg)' }}>
      {/* Console Alert Banner */}
      <div className="banner banner-warning" style={{ borderLeftWidth: 4 }}>
        <div>
          <strong>Deadlock Detected.</strong> Mathematical MNW limits exceeded. Please utilize the Force Allocation override options below to resolve conflicts.
        </div>
      </div>

      {error && (
        <div className="banner banner-error">
          {error}
        </div>
      )}

      {success && (
        <div className="banner banner-info">
          {success}
        </div>
      )}

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-lg)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
          {contestedAssets.length === 0 ? (
            <div className="archival-card text-center">
              <p className="text-muted">No contested assets found in this session.</p>
            </div>
          ) : (
            contestedAssets.map((asset) => {
              const bids = getBidsForAsset(asset.id);
              const selection = overrides[asset.id] || {};
              const currentAllocated = selection.allocated_to_id || '';
              const currentReason = selection.reason || '';

              return (
                <div
                  key={asset.id}
                  className="archival-card asset-conflict-card"
                  style={{ borderLeft: '4px solid var(--color-alert)' }}
                  data-testid={`conflict-card-${asset.id}`}
                >
                  <div style={{ display: 'flex', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
                    {asset.image_uri && (
                      <img
                        src={asset.image_uri}
                        alt={asset.title}
                        style={{
                          width: 120,
                          height: 120,
                          objectFit: 'cover',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--color-border)',
                        }}
                      />
                    )}
                    <div style={{ flex: 1, minWidth: 280 }}>
                      <h4 style={{ marginBottom: 'var(--space-xs)' }}>{asset.title}</h4>
                      <p className="text-xs text-muted" style={{ marginBottom: 'var(--space-sm)' }}>
                        Category: {asset.category || 'Uncategorized'} | Source: {asset.valuation_source || 'N/A'}
                      </p>
                      <p className="text-sm" style={{ marginBottom: 'var(--space-md)' }}>{asset.description}</p>
                    </div>
                  </div>

                  <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: 'var(--space-md) 0' }} />

                  {/* Overlapping valuations list */}
                  <div style={{ marginBottom: 'var(--space-md)' }}>
                    <h5 style={{ fontSize: '0.875rem', marginBottom: 'var(--space-sm)', color: 'var(--color-text-muted)' }}>
                      Heir Point Allocations (Overlapping Bids):
                    </h5>
                    {bids.length === 0 ? (
                      <p className="text-xs text-muted">No bids placed on this asset.</p>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)' }}>
                        {bids.map((bid, index) => (
                          <div
                            key={bid.heirId}
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              alignItems: 'center',
                              padding: 'var(--space-sm) var(--space-md)',
                              backgroundColor: index === 0 ? 'var(--color-primary-light)' : 'var(--color-bg)',
                              borderRadius: 'var(--radius-sm)',
                              border: '1px solid var(--color-border)',
                            }}
                          >
                            <div>
                              <span style={{ fontWeight: 600 }}>{bid.username}</span>
                              {bid.isReasoningShared && bid.reasoning && (
                                <span className="text-xs text-muted" style={{ display: 'block', fontStyle: 'italic', marginTop: 2 }}>
                                  "{bid.reasoning}"
                                </span>
                              )}
                            </div>
                            <span className="tabular-value" style={{ color: index === 0 ? 'var(--color-primary)' : 'inherit' }}>
                              {bid.points} pts
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Override controls */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)', marginTop: 'var(--space-md)' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 'var(--space-sm)' }}>
                      <div>
                        <label className="form-label" htmlFor={`override-select-${asset.id}`}>
                          Assign Beneficiary *
                        </label>
                        <select
                          id={`override-select-${asset.id}`}
                          className="form-input"
                          value={currentAllocated}
                          onChange={(e) => handleSelectionChange(asset.id, e.target.value)}
                        >
                          <option value="">-- Select Beneficiary --</option>
                          {heirs.map((heir) => (
                            <option key={heir.id} value={heir.id}>
                              {heir.username} ({heir.legal_first_name} {heir.legal_last_name})
                            </option>
                          ))}
                        </select>
                      </div>

                      {currentAllocated && (
                        <div>
                          <label className="form-label" htmlFor={`override-reason-${asset.id}`}>
                            Fiduciary Override Reason * (5-250 characters)
                          </label>
                          <textarea
                            id={`override-reason-${asset.id}`}
                            className="form-input form-textarea"
                            placeholder="Enter fiduciary justification basis (e.g. Decedent's Will instructions or mutual heir agreement)..."
                            value={currentReason}
                            onChange={(e) => handleReasonChange(asset.id, e.target.value)}
                            maxLength={250}
                            required
                          />
                          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
                            <span className="form-error">
                              {currentReason && currentReason.length < 5 ? 'Reason must be at least 5 characters.' : ''}
                            </span>
                            <span className="text-xs text-muted">
                              {currentReason.length} / 250
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {contestedAssets.length > 0 && (
          <button
            className="btn btn-primary btn-lg"
            type="submit"
            disabled={!isFormValid() || submitting}
            style={{ alignSelf: 'flex-start', marginTop: 'var(--space-md)' }}
          >
            {submitting ? 'Applying Override...' : 'Submit Override Allocations'}
          </button>
        )}
      </form>
    </div>
  );
}
