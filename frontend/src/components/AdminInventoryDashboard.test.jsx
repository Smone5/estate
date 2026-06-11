// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import AdminInventoryDashboard from './AdminInventoryDashboard';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

// Mock the Zustand store
vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('AdminInventoryDashboard Component', () => {
  const sessionId = 'session-123';
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      sessionStatus: 'SETUP',
      isAuthenticated: true,
    };

    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') {
        return selector(mockStoreState);
      }
      return mockStoreState;
    });

    // Reset fetch mocks
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Setup Phase Gate ────────────────────────────────────────────────────
  it('renders locked message when session is not in SETUP', () => {
    mockStoreState.sessionStatus = 'ACTIVE';

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    expect(screen.getByText('Inventory Dashboard Locked')).toBeInTheDocument();
    expect(
      screen.getByText(/only available during the Setup phase/),
    ).toBeInTheDocument();
  });

  // ── Loading State ───────────────────────────────────────────────────────
  it('renders loading state while fetching assets', async () => {
    // Return an unresolved promise to keep loading state
    global.fetch.mockImplementation(() => new Promise(() => {}));

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    expect(screen.getByText('Loading asset inventory...')).toBeInTheDocument();
  });

  // ── Legal Notice ────────────────────────────────────────────────────────
  it('renders the permanent legal scope notice', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      const notice = screen.getByTestId('legal-scope-notice');
      expect(notice).toBeInTheDocument();
      expect(notice.textContent).toContain(
        'This system is strictly for personal property and keepsakes',
      );
    });
  });

  // ── Asset List Rendering ────────────────────────────────────────────────
  it('renders asset cards from the API', async () => {
    const mockAssets = [
      {
        id: 'asset-1',
        title: 'Grandfather Clock',
        description: 'An antique oak clock',
        category: 'Furniture',
        valuation_min: 1500,
        valuation_max: 3000,
        valuation_source: 'Professional Appraisal',
        sentiment_tag: 'Heirloom',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: '/uploads/clock.jpg',
      },
      {
        id: 'asset-2',
        title: 'Pearl Necklace',
        description: 'A string of pearls',
        category: 'Jewelry',
        valuation_min: 500,
        valuation_max: 1200,
        valuation_source: 'Estate Sale Estimator',
        status: 'LIVE',
        ocr_status: 'COMPLETED',
        image_uri: null,
      },
    ];

    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByText('Grandfather Clock')).toBeInTheDocument();
    });

    expect(screen.getByText('Pearl Necklace')).toBeInTheDocument();
    expect(screen.getByText('$1,500 – $3,000')).toBeInTheDocument();
    expect(screen.getByText('$500 – $1,200')).toBeInTheDocument();
    expect(screen.getByTestId('asset-card-asset-1')).toBeInTheDocument();
    expect(screen.getByTestId('asset-card-asset-2')).toBeInTheDocument();
  });

  // ── OCR Processing Indicator ────────────────────────────────────────────
  it('displays OCR processing indicator for PROCESSING status', async () => {
    const mockAssets = [
      {
        id: 'asset-ocr',
        title: 'Painting',
        description: '',
        category: 'Art',
        valuation_min: 0,
        valuation_max: 0,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'PROCESSING',
        image_uri: null,
      },
    ];

    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(
        screen.getByTestId('ocr-processing-asset-ocr'),
      ).toBeInTheDocument();
      expect(screen.getByText('OCR extracting details...')).toBeInTheDocument();
    });
  });

  // ── Edit & Publish Flow ─────────────────────────────────────────────────
  it('opens edit form when Edit & Publish is clicked', async () => {
    const mockAssets = [
      {
        id: 'asset-edit',
        title: 'Vase',
        description: 'A ceramic vase',
        category: 'Other',
        valuation_min: 100,
        valuation_max: 300,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
      },
    ];

    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('edit-btn-asset-edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('edit-btn-asset-edit'));

    await waitFor(() => {
      expect(screen.getByTestId('edit-title-asset-edit')).toBeInTheDocument();
      expect(screen.getByTestId('edit-description-asset-edit')).toBeInTheDocument();
      expect(screen.getByTestId('edit-category-asset-edit')).toBeInTheDocument();
      expect(screen.getByTestId('publish-btn-asset-edit')).toBeInTheDocument();
    });

    // Verify pre-filled values
    expect(screen.getByTestId('edit-title-asset-edit').value).toBe('Vase');
    expect(screen.getByTestId('edit-description-asset-edit').value).toBe(
      'A ceramic vase',
    );
  });

  it('validates required fields and shows error on empty publish attempt', async () => {
    const mockAssets = [
      {
        id: 'asset-empty',
        title: '',
        description: '',
        category: 'Other',
        valuation_min: 0,
        valuation_max: 0,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
      },
    ];

    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('edit-btn-asset-empty')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('edit-btn-asset-empty'));

    await waitFor(() => {
      expect(screen.getByTestId('publish-btn-asset-empty')).toBeInTheDocument();
    });

    // Click publish with empty fields
    fireEvent.click(screen.getByTestId('publish-btn-asset-empty'));

    await waitFor(() => {
      expect(
        screen.getByText(/Cannot publish: missing required fields/),
      ).toBeInTheDocument();
    });
  });

  it('publishes asset successfully when all fields are valid', async () => {
    const stagedAsset = {
      id: 'asset-publish',
      title: 'Lamp',
      description: 'A vintage lamp',
      category: 'Furniture',
      valuation_min: 50,
      valuation_max: 200,
      valuation_source: 'Estate Sale Estimator',
      sentiment_tag: 'Vintage',
      status: 'STAGED',
      ocr_status: 'COMPLETED',
      image_uri: null,
    };

    let assetCallCount = 0;
    global.fetch.mockImplementation((url, options) => {
      if (url.includes('/assets')) {
        assetCallCount++;
        if (assetCallCount === 1) {
          // Initial load: return STAGED
          return Promise.resolve({
            ok: true,
            json: async () => [stagedAsset],
          });
        }
        // Refresh after publish: return LIVE
        return Promise.resolve({
          ok: true,
          json: async () => [{ ...stagedAsset, status: 'LIVE' }],
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      if (url.includes('/publish')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'LIVE' }),
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('edit-btn-asset-publish')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('edit-btn-asset-publish'));

    await waitFor(() => {
      expect(screen.getByTestId('publish-btn-asset-publish')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('publish-btn-asset-publish'));

    await waitFor(() => {
      // After publish, edit form closes and edit button is no longer present (asset is LIVE)
      expect(screen.queryByTestId('publish-btn-asset-publish')).not.toBeInTheDocument();
    });
  });

  // ── Delete Asset ────────────────────────────────────────────────────────
  it('deletes asset after confirmation', async () => {
    window.confirm = vi.fn(() => true);

    const mockAssets = [
      {
        id: 'asset-del',
        title: 'Old Chair',
        description: '',
        category: 'Furniture',
        valuation_min: 0,
        valuation_max: 0,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
      },
    ];

    let callCount = 0;
    global.fetch.mockImplementation((url, options) => {
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      if (options?.method === 'DELETE') {
        return Promise.resolve({ ok: true, json: async () => ({}) });
      }
      // Asset list
      callCount++;
      if (callCount === 1) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => [],
      });
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('delete-btn-asset-del')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('delete-btn-asset-del'));

    expect(window.confirm).toHaveBeenCalled();

    await waitFor(() => {
      expect(screen.queryByTestId('asset-card-asset-del')).not.toBeInTheDocument();
    });
  });

  // ── Pre-Allocation ──────────────────────────────────────────────────────
  it('opens pre-allocation dropdown and submits to API', async () => {
    const mockAssets = [
      {
        id: 'asset-pa',
        title: 'Ring',
        description: 'Gold ring',
        category: 'Jewelry',
        valuation_min: 500,
        valuation_max: 1000,
        valuation_source: 'Professional Appraisal',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
      },
    ];

    const mockHeirs = [
      { id: 'heir-1', username: 'Alice', legal_first_name: 'Alice', legal_last_name: 'Smith' },
      { id: 'heir-2', username: 'Bob', legal_first_name: 'Bob', legal_last_name: 'Jones' },
    ];

    let assetFetchCount = 0;
    global.fetch.mockImplementation((url, options) => {
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockHeirs,
        });
      }
      if (url.includes('/pre-allocate')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ status: 'PRE_ALLOCATED' }),
        });
      }
      if (url.includes('/assets')) {
        assetFetchCount++;
        const updatedAssets = assetFetchCount > 1
          ? [{ ...mockAssets[0], status: 'PRE_ALLOCATED', pre_allocated_to_heir_name: 'Alice' }]
          : mockAssets;
        return Promise.resolve({
          ok: true,
          json: async () => updatedAssets,
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('pre-allocate-btn-asset-pa')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('pre-allocate-btn-asset-pa'));

    await waitFor(() => {
      expect(screen.getByTestId('pre-allocate-select-asset-pa')).toBeInTheDocument();
    });

    // Select heir
    fireEvent.change(screen.getByTestId('pre-allocate-select-asset-pa'), {
      target: { value: 'heir-1' },
    });

    fireEvent.click(screen.getByTestId('confirm-pre-allocate-asset-pa'));

    await waitFor(() => {
      expect(screen.queryByTestId('pre-allocate-select-asset-pa')).not.toBeInTheDocument();
    });
  });

  // ── Audio Upload Flow ──────────────────────────────────────────────────
  it('shows audio upload UI when Add Voice Story is clicked', async () => {
    const mockAssets = [
      {
        id: 'asset-audio',
        title: 'Music Box',
        description: '',
        category: 'Other',
        valuation_min: 100,
        valuation_max: 300,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
        audio_uri: null,
      },
    ];

    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByTestId('audio-btn-asset-audio')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('audio-btn-asset-audio'));

    await waitFor(() => {
      expect(screen.getByTestId('audio-file-input-asset-audio')).toBeInTheDocument();
    });
  });

  // ── Empty State ─────────────────────────────────────────────────────────
  it('renders empty state when no assets exist', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByText('No Assets Staged')).toBeInTheDocument();
    });
  });

  // ── Pre-allocated indicator ─────────────────────────────────────────────
  it('displays pre-allocated heir name on PRE_ALLOCATED assets', async () => {
    const mockAssets = [
      {
        id: 'asset-prea',
        title: 'Watch',
        description: 'Vintage watch',
        category: 'Jewelry',
        valuation_min: 1000,
        valuation_max: 2000,
        valuation_source: 'Professional Appraisal',
        status: 'PRE_ALLOCATED',
        pre_allocated_to_heir_name: 'Charlie',
        ocr_status: 'COMPLETED',
        image_uri: null,
      },
    ];

    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByText('Pre-Allocated: Charlie')).toBeInTheDocument();
    });
  });

  // ── Spoken Story Indicator ──────────────────────────────────────────────
  it('shows spoken story indicator and remove audio button when audio_uri exists', async () => {
    const mockAssets = [
      {
        id: 'asset-with-audio',
        title: 'Storybook',
        description: '',
        category: 'Other',
        valuation_min: 50,
        valuation_max: 100,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
        audio_uri: '/uploads/audio.webm',
      },
    ];

    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockAssets,
        });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    await waitFor(() => {
      expect(screen.getByText('🎙 Spoken Story Recorded')).toBeInTheDocument();
      expect(screen.getByTestId('delete-audio-btn-asset-with-audio')).toBeInTheDocument();
    });
  });
});