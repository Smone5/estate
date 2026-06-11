import React, { useState, useCallback, useMemo } from 'react';
import { useMediationStore } from '../store/useMediationStore';

const API_BASE = '';

const CATEGORIES = [
  { key: 'Jewelry', label: 'Jewelry', border: '#C29F53' },
  { key: 'Furniture', label: 'Furniture', border: '#8E7558' },
  { key: 'Art', label: 'Art', border: '#7E6C84' },
  { key: 'Other', label: 'Other', border: '#64748B' },
];

const SORT_OPTIONS = [
  { value: 'relevance', label: 'Relevance' },
  { value: 'points_high', label: 'My Points (High → Low)' },
  { value: 'points_low', label: 'My Points (Low → High)' },
  { value: 'title_asc', label: 'Title (A → Z)' },
  { value: 'title_desc', label: 'Title (Z → A)' },
  { value: 'category', label: 'Category' },
];

const ALLOCATION_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'allocated', label: 'Allocated (>0 pts)' },
  { value: 'unallocated', label: 'Unallocated (0 pts)' },
  { value: 'pre_allocated', label: 'Pre-Allocated' },
];

export default function SemanticSearch() {
  const assets = useMediationStore((s) => s.assets);
  const valuations = useMediationStore((s) => s.valuations);
  const sessionId = useMediationStore((s) => s.session_id);

  // ── Local state ──────────────────────────────────────────────────────
  const [query, setQuery] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [selectedCategories, setSelectedCategories] = useState(new Set());
  const [allocationFilter, setAllocationFilter] = useState('all');
  const [spokenProvenance, setSpokenProvenance] = useState(false);
  const [sharedStories, setSharedStories] = useState(false);
  const [sortBy, setSortBy] = useState('relevance');
  const [results, setResults] = useState(null); // null = use store assets; array = search results
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);

  // ── Derived state ────────────────────────────────────────────────────
  const displayAssets = results || assets;

  const filteredAssets = useMemo(() => {
    let filtered = [...displayAssets];

    // Category filter
    if (selectedCategories.size > 0) {
      filtered = filtered.filter((a) => selectedCategories.has(a.category));
    }

    // Allocation filter
    if (allocationFilter === 'allocated') {
      filtered = filtered.filter((a) => {
        const val = valuations[a.id];
        return val && val.points > 0;
      });
    } else if (allocationFilter === 'unallocated') {
      filtered = filtered.filter((a) => {
        const val = valuations[a.id];
        return !val || val.points === 0;
      });
    } else if (allocationFilter === 'pre_allocated') {
      filtered = filtered.filter((a) => a.status === 'PRE_ALLOCATED');
    }

    // Spoken provenance toggle
    if (spokenProvenance) {
      filtered = filtered.filter((a) => a.audio_uri);
    }

    // Shared stories toggle
    if (sharedStories) {
      filtered = filtered.filter((a) => a.shared_memories && a.shared_memories.length > 0);
    }

    // Sort
    filtered.sort((a, b) => {
      switch (sortBy) {
        case 'points_high': {
          const aPts = valuations[a.id]?.points || 0;
          const bPts = valuations[b.id]?.points || 0;
          return bPts - aPts;
        }
        case 'points_low': {
          const aPts = valuations[a.id]?.points || 0;
          const bPts = valuations[b.id]?.points || 0;
          return aPts - bPts;
        }
        case 'title_asc':
          return (a.title || '').localeCompare(b.title || '');
        case 'title_desc':
          return (b.title || '').localeCompare(a.title || '');
        case 'category':
          return (a.category || '').localeCompare(b.category || '');
        case 'relevance':
        default: {
          // Sort by similarity score (descending) if present
          const aScore = a._similarity ?? 0;
          const bScore = b._similarity ?? 0;
          return bScore - aScore;
        }
      }
    });

    return filtered;
  }, [displayAssets, valuations, selectedCategories, allocationFilter, spokenProvenance, sharedStories, sortBy]);

  // ── Confidence threshold ─────────────────────────────────────────────
  const hasSearch = results !== null;
  const highConfidenceAssets = hasSearch
    ? filteredAssets.filter((a) => a._similarity === undefined || a._similarity >= 0.75)
    : filteredAssets;

  const showZeroMatch = hasSearch && query.trim() && highConfidenceAssets.length === 0;

  // ── Search handler ───────────────────────────────────────────────────
  const handleSearch = useCallback(async () => {
    if (!query.trim()) {
      setResults(null);
      setSearchError(null);
      return;
    }

    if (!sessionId) return;

    setSearching(true);
    setSearchError(null);

    try {
      const params = new URLSearchParams();
      params.set('q', query.trim());
      if (selectedCategories.size > 0) {
        params.set('category', [...selectedCategories].join(','));
      }

      const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/assets?${params.toString()}`);
      if (!res.ok) throw new Error(`Search failed (${res.status})`);

      const data = await res.json();
      setResults(data.assets || data);
    } catch (err) {
      setSearchError(err.message);
      setResults(null);
    } finally {
      setSearching(false);
    }
  }, [query, sessionId, selectedCategories]);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Enter') {
        handleSearch();
      }
    },
    [handleSearch],
  );

  const handleClearSearch = useCallback(() => {
    setQuery('');
    setResults(null);
    setSearchError(null);
  }, []);

  // ── Category toggle ──────────────────────────────────────────────────
  const toggleCategory = useCallback((cat) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) {
        next.delete(cat);
      } else {
        next.add(cat);
      }
      return next;
    });
  }, []);

  // ── Ask the Mediator ─────────────────────────────────────────────────
  const handleAskMediator = useCallback(() => {
    // Inject the search query as a chat message to the mediator
    const store = useMediationStore.getState();
    store.addMessage({
      sender: 'heir',
      text: `Did you find any "${query.trim()}" in the estate?`,
    });
  }, [query]);

  // ── Render ───────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 'var(--space-md)', height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Search bar */}
      <div style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-md)' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <input
            type="text"
            className="form-input"
            placeholder="Search assets by name, description, or story..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            style={{ paddingRight: query ? '2.5rem' : undefined }}
          />
          {query && (
            <button
              type="button"
              onClick={handleClearSearch}
              style={{
                position: 'absolute',
                right: 8,
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--color-text)',
                opacity: 0.5,
                fontSize: '1rem',
                lineHeight: 1,
                padding: 4,
              }}
              aria-label="Clear search"
            >
              ✕
            </button>
          )}
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleSearch}
          disabled={searching || !query.trim()}
        >
          {searching ? 'Searching...' : 'Search'}
        </button>
        <button
          type="button"
          className={`btn ${filtersOpen ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setFiltersOpen(!filtersOpen)}
          aria-label="Toggle filters"
        >
          Filters
        </button>
      </div>

      {/* Filter panel */}
      {filtersOpen && (
        <div
          className="archival-card"
          style={{ marginBottom: 'var(--space-md)', padding: 'var(--space-md)' }}
        >
          <h4 style={{ marginBottom: 'var(--space-sm)' }}>Category</h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-xs)', marginBottom: 'var(--space-md)' }}>
            {CATEGORIES.map((cat) => (
              <button
                key={cat.key}
                type="button"
                onClick={() => toggleCategory(cat.key)}
                style={{
                  border: `1px solid ${cat.border}`,
                  borderRadius: 16,
                  padding: '4px 12px',
                  fontSize: '0.813rem',
                  backgroundColor: selectedCategories.has(cat.key) ? cat.border : 'transparent',
                  color: selectedCategories.has(cat.key) ? '#FFFFFF' : cat.border,
                  cursor: 'pointer',
                  transition: 'all 0.3s ease-in-out',
                }}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <h4 style={{ marginBottom: 'var(--space-sm)' }}>Allocation</h4>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-xs)', marginBottom: 'var(--space-md)' }}>
            {ALLOCATION_FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setAllocationFilter(f.value)}
                style={{
                  border: '1px solid var(--color-border)',
                  borderRadius: 16,
                  padding: '4px 12px',
                  fontSize: '0.813rem',
                  backgroundColor: allocationFilter === f.value ? 'var(--color-primary)' : 'transparent',
                  color: allocationFilter === f.value ? '#FFFFFF' : 'var(--color-text)',
                  cursor: 'pointer',
                  transition: 'all 0.3s ease-in-out',
                }}
              >
                {f.label}
              </button>
            ))}
          </div>

          <h4 style={{ marginBottom: 'var(--space-sm)' }}>Special Filters</h4>
          <div style={{ display: 'flex', gap: 'var(--space-md)', marginBottom: 'var(--space-md)' }}>
            <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)' }}>
              <input
                type="checkbox"
                checked={spokenProvenance}
                onChange={(e) => setSpokenProvenance(e.target.checked)}
              />
              <span className="text-sm">Spoken Provenance</span>
            </label>
            <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)' }}>
              <input
                type="checkbox"
                checked={sharedStories}
                onChange={(e) => setSharedStories(e.target.checked)}
              />
              <span className="text-sm">Shared Stories</span>
            </label>
          </div>

          <h4 style={{ marginBottom: 'var(--space-sm)' }}>Sort By</h4>
          <select
            className="form-input"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{ maxWidth: 240 }}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Sort dropdown (compact, always visible when filters closed) */}
      {!filtersOpen && (
        <div style={{ marginBottom: 'var(--space-md)', display: 'flex', justifyContent: 'flex-end' }}>
          <select
            className="form-input"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{ maxWidth: 200, fontSize: '0.813rem' }}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Search error */}
      {searchError && (
        <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
          {searchError}
        </div>
      )}

      {/* Zero-match fallback */}
      {showZeroMatch && (
        <div className="archival-card" style={{ textAlign: 'center', marginBottom: 'var(--space-lg)' }}>
          <p className="text-muted" style={{ marginBottom: 'var(--space-md)' }}>
            We couldn't find a close match for <strong>"{query.trim()}"</strong>.
            Try searching by general category (e.g. "Furniture") or ask the Mediator Agent.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleAskMediator}
          >
            Ask the Mediator
          </button>
        </div>
      )}

      {/* Asset gallery grid */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: 'var(--space-md)',
          alignContent: 'start',
        }}
      >
        {highConfidenceAssets.map((asset) => {
          const val = valuations[asset.id];
          const similarity = asset._similarity;
          const showConfidence = hasSearch && similarity >= 0.75;

          return (
            <div
              key={asset.id}
              className="archival-card"
              style={{ padding: 0, overflow: 'hidden', position: 'relative' }}
            >
              {/* Image thumbnail */}
              {asset.image_uri && (
                <div style={{ aspectRatio: '4/3', overflow: 'hidden' }}>
                  <img
                    src={asset.image_uri}
                    alt={asset.title || 'Asset'}
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'cover',
                    }}
                    loading="lazy"
                  />
                </div>
              )}

              {/* Confidence pill */}
              {showConfidence && (
                <span
                  style={{
                    position: 'absolute',
                    top: 8,
                    right: 8,
                    backgroundColor: 'var(--color-primary)',
                    color: '#FFFFFF',
                    padding: '2px 8px',
                    borderRadius: 12,
                    fontSize: '0.75rem',
                    fontWeight: 600,
                  }}
                >
                  {Math.round(similarity * 100)}% Match
                </span>
              )}

              {/* Card content */}
              <div style={{ padding: 'var(--space-md)' }}>
                <h4 style={{ marginBottom: 'var(--space-xs)', fontSize: '0.938rem' }}>
                  {asset.title || 'Untitled Asset'}
                </h4>

                {/* Category badge */}
                {asset.category && (
                  <span
                    style={{
                      display: 'inline-block',
                      border: `1px solid ${CATEGORIES.find((c) => c.key === asset.category)?.border || 'var(--color-border)'}`,
                      borderRadius: 16,
                      padding: '2px 8px',
                      fontSize: '0.688rem',
                      color: 'var(--color-text)',
                      marginBottom: 'var(--space-xs)',
                    }}
                  >
                    {asset.category}
                  </span>
                )}

                {/* Points display */}
                {val && (
                  <p className="text-sm tabular-value" style={{ marginBottom: 0 }}>
                    {val.points || 0} pts
                  </p>
                )}

                {/* Spoken provenance indicator */}
                {asset.audio_uri && (
                  <span
                    className="text-sm text-muted"
                    style={{ display: 'inline-block', marginTop: 'var(--space-xs)' }}
                  >
                    🎤 Spoken Story
                  </span>
                )}

                {/* Pre-allocated badge */}
                {asset.status === 'PRE_ALLOCATED' && (
                  <span
                    style={{
                      display: 'inline-block',
                      backgroundColor: 'var(--color-alert-light)',
                      color: 'var(--color-alert)',
                      padding: '2px 6px',
                      borderRadius: 4,
                      fontSize: '0.688rem',
                      fontWeight: 600,
                      marginTop: 'var(--space-xs)',
                    }}
                  >
                    Pre-Allocated
                  </span>
                )}
              </div>
            </div>
          );
        })}

        {/* Empty gallery state (no search, no assets) */}
        {!hasSearch && filteredAssets.length === 0 && (
          <div className="archival-card" style={{ textAlign: 'center', gridColumn: '1 / -1', padding: 'var(--space-2xl)' }}>
            <p className="text-muted">
              No assets have been published yet. The Executor is preparing the estate catalog.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}