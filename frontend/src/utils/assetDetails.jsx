import React from 'react';

export function getDisplayDescription(asset) {
  const description = asset?.description?.trim();
  if (!description) return '';

  const normalized = description.toLowerCase();
  if (
    normalized === 'ocr extracting details...' ||
    normalized === 'ai appraising...' ||
    normalized.startsWith('ocr extracting details')
  ) {
    return '';
  }

  return description;
}

export function parseDescriptionJson(asset) {
  try {
    if (!asset?.description_json) return {};
    return typeof asset.description_json === 'string'
      ? JSON.parse(asset.description_json)
      : asset.description_json;
  } catch {
    return {};
  }
}

function normalizeDetailValue(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).join('\n');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .filter(([, detail]) => detail != null && `${detail}`.trim())
      .map(([key, detail]) => `${key}: ${detail}`)
      .join('\n');
  }
  return typeof value === 'string' ? value.trim() : '';
}

function formatNumber(value) {
  if (value == null || value === '') return '';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '';
  return Number.isInteger(numeric) ? `${numeric}` : `${numeric.toFixed(1).replace(/\.0$/, '')}`;
}

export function getAssetDimensionDetails(asset) {
  const djson = parseDescriptionJson(asset);
  const dimensions = djson.dimensions && typeof djson.dimensions === 'object'
    ? djson.dimensions
    : {};
  const length = asset?.length_in ?? dimensions.length_in;
  const width = asset?.width_in ?? dimensions.width_in;
  const height = asset?.height_in ?? dimensions.height_in;
  const weight = asset?.weight_lb ?? dimensions.weight_lb;
  const parts = [];

  const sizeParts = [
    formatNumber(length),
    formatNumber(width),
    formatNumber(height),
  ];
  if (sizeParts.some(Boolean)) {
    parts.push(`Size: ${sizeParts.map((part) => part || '?').join(' x ')} in`);
  }
  const weightLabel = formatNumber(weight);
  if (weightLabel) {
    parts.push(`Weight: ${weightLabel} lb`);
  }

  const confidence = asset?.dimension_confidence ?? dimensions.confidence ?? dimensions.dimension_confidence;
  const source = asset?.dimension_source ?? dimensions.source ?? dimensions.dimension_source;
  const notes = asset?.dimension_notes ?? dimensions.notes ?? dimensions.dimension_notes;
  const metaParts = [source, confidence ? `${confidence} confidence` : ''].filter(Boolean);
  if (metaParts.length) parts.push(metaParts.join(' · '));
  if (notes) parts.push(notes);

  return parts.join('\n');
}

export function getStructuredAssetDetails(asset) {
  const djson = parseDescriptionJson(asset);
  return {
    dimensions: getAssetDimensionDetails(asset),
    specifications: normalizeDetailValue(asset?.specifications || djson.specifications),
    conditionReport: normalizeDetailValue(asset?.condition_report || djson.condition_report),
    keywords: normalizeDetailValue(asset?.keywords || djson.keywords),
  };
}

export function hasStructuredAssetDetails(details) {
  return Boolean(details.dimensions || details.specifications || details.conditionReport || details.keywords);
}

export function StructuredAssetDetails({ details, compact = false }) {
  const rows = [
    ['Logistics', details.dimensions],
    ['Specifications', details.specifications],
    ['Condition Report', details.conditionReport],
    ['Search Keywords', details.keywords],
  ].filter(([, value]) => value);

  if (rows.length === 0) return null;

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: compact ? '6px' : 'var(--space-sm)',
      marginTop: compact ? 'var(--space-xs)' : 0,
    }}>
      {rows.map(([label, value]) => (
        <div key={label}>
          <p className="text-xs" style={{
            marginBottom: '2px',
            color: 'var(--color-text)',
            fontWeight: 700,
          }}>
            {label}
          </p>
          <p className="text-sm text-muted" style={{
            margin: 0,
            lineHeight: 1.45,
            whiteSpace: 'pre-line',
          }}>
            {value}
          </p>
        </div>
      ))}
    </div>
  );
}
