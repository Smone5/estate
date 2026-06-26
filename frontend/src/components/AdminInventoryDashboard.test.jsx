// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import React from 'react';
import AdminInventoryDashboard from './AdminInventoryDashboard';
import { useMediationStore } from '../store/useMediationStore';
import {
  deleteStagingItem,
  saveStagingItem,
  updateStagingItemStatus,
} from '../utils/stagingDB';
import '@testing-library/jest-dom';

// Mock indexedDB for jsdom
const indexedDBStore = {};
global.indexedDB = {
  open: vi.fn(() => {
    const request = {
      result: {
        objectStoreNames: { contains: () => false },
        createObjectStore: vi.fn(() => ({
          createIndex: vi.fn(),
        })),
        transaction: vi.fn(() => ({
          objectStore: vi.fn(() => ({
            put: vi.fn(() => ({
              onsuccess: null,
            })),
            get: vi.fn(() => ({
              onsuccess: null,
              result: null,
            })),
            getAll: vi.fn(() => ({
              onsuccess: null,
              result: [],
            })),
            index: vi.fn(() => ({
              getAll: vi.fn(() => ({
                onsuccess: null,
                result: [],
              })),
              count: vi.fn(() => ({
                onsuccess: null,
                result: 0,
              })),
            })),
            delete: vi.fn(() => ({
              onsuccess: null,
            })),
            clear: vi.fn(() => ({
              onsuccess: null,
            })),
          })),
          oncomplete: null,
        })),
      },
      onupgradeneeded: null,
      onsuccess: null,
      onerror: null,
    };
    return request;
  }),
};

// Mock crypto.randomUUID
if (!global.crypto) {
  global.crypto = {};
}
global.crypto.randomUUID = vi.fn(() => 'test-uuid-1234');

// Mock createImageBitmap (used by imageCompression)
global.createImageBitmap = vi.fn(() =>
  Promise.resolve({
    width: 100,
    height: 100,
    close: vi.fn(),
  })
);

// Mock canvas
HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
  translate: vi.fn(),
  rotate: vi.fn(),
  drawImage: vi.fn(),
  filter: '',
}));
HTMLCanvasElement.prototype.toDataURL = vi.fn(() => 'data:image/webp;base64,test');
HTMLCanvasElement.prototype.toBlob = vi.fn((callback, type, quality) => {
  callback(new Blob(['test'], { type: type || 'image/webp' }));
});

class MockImage {
  constructor() {
    this.naturalWidth = 100;
    this.naturalHeight = 100;
    this.onload = null;
    this.onerror = null;
    this.crossOrigin = '';
  }

  set src(value) {
    this._src = value;
    setTimeout(() => this.onload && this.onload(), 0);
  }

  get src() {
    return this._src;
  }
}
global.Image = MockImage;
window.Image = MockImage;

// Mock stagingDB
vi.mock('../utils/stagingDB', () => ({
  saveStagingItem: vi.fn(() => Promise.resolve()),
  loadStagingItems: vi.fn(() => Promise.resolve([])),
  loadPendingStagingItems: vi.fn(() => Promise.resolve([])),
  deleteStagingItem: vi.fn(() => Promise.resolve()),
  updateStagingItemStatus: vi.fn(() => Promise.resolve()),
  clearStagingItems: vi.fn(() => Promise.resolve()),
  getPendingCount: vi.fn(() => Promise.resolve(0)),
}));

// Mock imageCompression
vi.mock('../utils/imageCompression', () => ({
  compressImage: vi.fn((file) => Promise.resolve(new Blob(['compressed'], { type: 'image/webp' }))),
  shouldCompress: vi.fn(() => true),
  autoCompress: vi.fn((file) => Promise.resolve({ blob: new Blob(['compressed'], { type: 'image/webp' }), wasCompressed: true })),
}));

// Mock AdminVoiceRecorder
vi.mock('./AdminVoiceRecorder', () => ({
  default: ({ assetId, onSaved }) => (
    <div data-testid={`voice-recorder-${assetId || 'staging'}`}>
      <button
        type="button"
        data-testid="mock-recording-save"
        onClick={() => onSaved && onSaved(new Blob(['audio'], { type: 'audio/webm' }))}
      >
        Simulate Record
      </button>
    </div>
  ),
}));

vi.mock('react-easy-crop', () => ({
  default: ({ onCropComplete, style }) => {
    React.useEffect(() => {
      onCropComplete?.(null, { x: 0, y: 0, width: 80, height: 60 });
    }, []);
    return (
      <div
        data-testid="mock-image-cropper"
        data-filter={style?.mediaStyle?.filter || ''}
      />
    );
  },
}));

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
    global.URL.createObjectURL = vi.fn(() => 'blob:http://localhost/test-preview');
    global.URL.revokeObjectURL = vi.fn();

    // Mock navigator.mediaDevices.getUserMedia so tests fall back to file picker
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: vi.fn(() => Promise.reject(new Error('Test env — no camera'))),
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Setup Phase Gate ────────────────────────────────────────────────────
  it('renders locked message when session is not in SETUP or ACTIVE', () => {
    mockStoreState.sessionStatus = 'FINALIZED';

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    expect(screen.getByText('Inventory Dashboard Locked')).toBeInTheDocument();
    expect(
      screen.getByText(/only available during the Setup and Active phases/),
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

  it('renders flexible quick capture with AI describe toggle', async () => {
    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets')) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);
    fireEvent.click(await screen.findByTestId('quick-capture-toggle'));

    await waitFor(() => {
      expect(screen.getByTestId('add-staging-photo')).toBeInTheDocument();
    });

    expect(screen.getByText('Add first photo')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Take photo' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upload images' })).toBeInTheDocument();
    expect(screen.getByTestId('auto-describe-toggle')).toBeChecked();
    expect(screen.queryByText(/Slot 1/)).not.toBeInTheDocument();
    expect(screen.getByTestId('stage-from-slots-btn')).toBeDisabled();
  });

  it('explains photo labels in plain language', async () => {
    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets') || url.includes('/heirs')) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);
    fireEvent.click(await screen.findByTestId('quick-capture-toggle'));

    const helpButton = await screen.findByRole('button', {
      name: 'What do the photo labels mean?',
    });
    expect(helpButton).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(helpButton);

    expect(helpButton).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('region', { name: 'Photo label explanation' })).toBeInTheDocument();
    expect(screen.getByText('Maker / brand mark')).toBeInTheDocument();
    expect(screen.getByText(/signature, label, stamp, serial number/i)).toBeInTheDocument();
    expect(screen.getByText('Primary photo')).toBeInTheDocument();
  });

  it('adds uploaded images to the quick-capture preview stack', async () => {
    global.fetch.mockImplementation((url) => {
      if (url.includes('/assets') || url.includes('/heirs')) {
        return Promise.resolve({ ok: true, json: async () => [] });
      }
      return Promise.reject(new Error('Unknown URL'));
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);
    fireEvent.click(await screen.findByTestId('quick-capture-toggle'));

    const fileInput = await screen.findByLabelText('Upload item images');
    const file = new File(['photo'], 'vase.jpg', { type: 'image/jpeg' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByTestId('staging-photo-0')).toBeInTheDocument();
    });
    expect(screen.getByAltText('Front')).toHaveAttribute(
      'src',
      'blob:http://localhost/test-preview',
    );
    expect(screen.getByRole('button', { name: 'Maker / brand mark' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Damage / wear' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Size reference' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close-up detail' })).toBeInTheDocument();
    expect(screen.getByTestId('stage-from-slots-btn')).toBeEnabled();
  });

  it('finishes staging after the server confirms the upload', async () => {
    global.fetch.mockImplementation((url, options = {}) => {
      if (options.method === 'POST' && url.includes('/assets/stage')) {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({ asset_id: 'test-uuid-1234', status: 'STAGED' }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);
    fireEvent.click(await screen.findByTestId('quick-capture-toggle'));

    const fileInput = await screen.findByLabelText('Upload item images');
    fireEvent.change(fileInput, {
      target: {
        files: [new File(['photo'], 'vase.jpg', { type: 'image/jpeg' })],
      },
    });

    const stageButton = await screen.findByTestId('stage-from-slots-btn');
    await waitFor(() => expect(stageButton).toBeEnabled());
    fireEvent.click(stageButton);

    await waitFor(() => {
      expect(screen.getByText('✅ Staged!')).toBeInTheDocument();
    });
    expect(saveStagingItem).toHaveBeenCalled();
    expect(deleteStagingItem).toHaveBeenCalledWith('test-uuid-1234');
    expect(updateStagingItemStatus).not.toHaveBeenCalledWith('test-uuid-1234', 'uploaded');
    expect(stageButton).toHaveTextContent('📤 Stage Item');
  });

  it('keeps the inventory workspace visible while the post-stage refresh is pending', async () => {
    let resolveRefresh;
    const pendingRefresh = new Promise((resolve) => {
      resolveRefresh = resolve;
    });
    let assetRequestCount = 0;

    global.fetch.mockImplementation((url, options = {}) => {
      if (options.method === 'POST' && url.includes('/assets/stage')) {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({ asset_id: 'test-uuid-1234', status: 'STAGED' }),
        });
      }
      if (url.includes('/assets')) {
        assetRequestCount += 1;
        if (assetRequestCount > 1) return pendingRefresh;
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);
    fireEvent.click(await screen.findByTestId('quick-capture-toggle'));

    fireEvent.change(await screen.findByLabelText('Upload item images'), {
      target: {
        files: [new File(['photo'], 'vase.jpg', { type: 'image/jpeg' })],
      },
    });

    const stageButton = await screen.findByTestId('stage-from-slots-btn');
    await waitFor(() => expect(stageButton).toBeEnabled());
    fireEvent.click(stageButton);

    await waitFor(() => {
      expect(screen.getByText('✅ Staged!')).toBeInTheDocument();
    });
    expect(screen.queryByText('Loading asset inventory...')).not.toBeInTheDocument();
    expect(screen.getByTestId('admin-inventory-dashboard')).toBeInTheDocument();

    resolveRefresh({ ok: true, json: async () => [] });
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
      expect(screen.getByTestId('asset-card-asset-1')).toBeInTheDocument();
      expect(screen.getByTestId('asset-card-asset-2')).toBeInTheDocument();
    });

    const card1 = screen.getByTestId('asset-card-asset-1');
    expect(within(card1).getByText('Grandfather Clock')).toBeInTheDocument();
    expect(within(card1).getByText('$1,500 – $3,000')).toBeInTheDocument();

    const card2 = screen.getByTestId('asset-card-asset-2');
    expect(within(card2).getByText('Pearl Necklace')).toBeInTheDocument();
    expect(within(card2).getByText('$500 – $1,200')).toBeInTheDocument();
  });

  it('expands long descriptions and previews an item as an heir', async () => {
    const longDescription = 'This detailed scale model has a painted red hull, fishing rigging, netting, and small cabin details. It should remain readable for the executor and visible in full when checking how heirs will review the item.';
    const specifications = '- Estimated materials: Wood hull, painted finish, twine rigging\n- Primary colors: Deep red hull accents';
    const conditionReport = 'Decorative item. The structure appears stable and displays expected wear for its apparent age.';
    const keywords = 'Model boat, Nautical decor, Fishing vessel';
    const mockAssets = [
      {
        id: 'asset-preview',
        title: 'Model Fishing Boat',
        description: longDescription,
        description_json: JSON.stringify({
          specifications,
          condition_report: conditionReport,
          keywords,
        }),
        category: 'Living Room',
        valuation_min: 40,
        valuation_max: 120,
        valuation_source: 'AI Valuation Range (Estimate)',
        sentiment_tag: 'Heirloom, Handmade',
        status: 'STAGED',
        image_uri: 'static/uploads/boat.webp',
        images: [
          {
            id: 'image-primary',
            image_uri: 'static/uploads/boat.webp',
            is_primary: true,
            angle_label: 'Primary',
          },
        ],
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
      expect(screen.getByTestId('asset-card-asset-preview')).toBeInTheDocument();
    });

    const toggle = screen.getByTestId('toggle-description-asset-preview');
    expect(toggle).toHaveTextContent('Show more');
    expect(screen.queryByText('Specifications')).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveTextContent('Show less');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Specifications')).toBeInTheDocument();
    expect(screen.getByText(/Estimated materials: Wood hull/)).toBeInTheDocument();
    expect(screen.getByText(/Primary colors: Deep red hull accents/)).toBeInTheDocument();
    expect(screen.getByText('Condition Report')).toBeInTheDocument();
    expect(screen.getByText(conditionReport)).toBeInTheDocument();
    expect(screen.getByText('Search Keywords')).toBeInTheDocument();
    expect(screen.getByText(keywords)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('preview-heir-btn-asset-preview'));

    await waitFor(() => {
      expect(screen.getByTestId('heir-preview-modal')).toBeInTheDocument();
    });

    const dialog = screen.getByRole('dialog', { name: /Model Fishing Boat/ });
    expect(dialog).toBeInTheDocument();
    expect(screen.getAllByText(longDescription).length).toBeGreaterThan(0);
    expect(within(dialog).getByText('Specifications')).toBeInTheDocument();
    expect(within(dialog).getByText(/Estimated materials: Wood hull/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Primary colors: Deep red hull accents/)).toBeInTheDocument();
    expect(within(dialog).getByText('Condition Report')).toBeInTheDocument();
    expect(within(dialog).getByText(conditionReport)).toBeInTheDocument();
    expect(within(dialog).getByText('Search Keywords')).toBeInTheDocument();
    expect(within(dialog).getByText(keywords)).toBeInTheDocument();
    expect(within(dialog).getByText('$40 – $120')).toBeInTheDocument();
  });

  // ── OCR Processing State ────────────────────────────────────────────────
  it('keeps OCR processing status silent in the asset card', async () => {
    const mockAssets = [
      {
        id: 'asset-ocr',
        title: 'Painting',
        description: 'OCR extracting details...',
        category: 'Art',
        valuation_min: 0,
        valuation_max: 0,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'PROCESSING',
        description_json: '{"review_required":false}',
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
      expect(screen.getByTestId('asset-card-asset-ocr')).toBeInTheDocument();
    });

    expect(screen.queryByTestId('ocr-processing-asset-ocr')).not.toBeInTheDocument();
    expect(screen.queryByText(/AI appraising/)).not.toBeInTheDocument();
    expect(screen.queryByText(/OCR extracting details/)).not.toBeInTheDocument();
    expect(screen.queryByText(/AI could not identify details/)).not.toBeInTheDocument();
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

    const deleteDialog = screen.getByRole('dialog', { name: 'Permanently delete this asset?' });
    expect(deleteDialog).toBeInTheDocument();
    expect(within(deleteDialog).getByText('Old Chair')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-delete-asset'));

    await waitFor(() => {
      expect(screen.queryByTestId('asset-card-asset-del')).not.toBeInTheDocument();
    });
  });

  it('keeps the delete dialog open when deletion fails', async () => {
    const mockAssets = [{
      id: 'asset-delete-fails',
      title: 'Protected Vase',
      category: 'Art',
      status: 'STAGED',
      ocr_status: 'COMPLETED',
      image_uri: 'static/uploads/vase.webp',
    }];

    global.fetch.mockImplementation((url, options = {}) => {
      if (options.method === 'DELETE') {
        return Promise.resolve({
          ok: false,
          status: 400,
          json: async () => ({ detail: 'This asset cannot be deleted right now.' }),
        });
      }
      if (url.includes('/assets')) {
        return Promise.resolve({ ok: true, json: async () => mockAssets });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    });

    render(<AdminInventoryDashboard sessionId={sessionId} />);

    fireEvent.click(await screen.findByTestId('delete-btn-asset-delete-fails'));
    fireEvent.click(screen.getByTestId('confirm-delete-asset'));

    await waitFor(() => {
      expect(screen.getByText('This asset cannot be deleted right now.')).toBeInTheDocument();
    });
    expect(screen.getByTestId('delete-asset-dialog')).toBeInTheDocument();
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
  it('shows audio upload UI when Edit is clicked and drawer opens', async () => {
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
      expect(screen.getByTestId('edit-btn-asset-audio')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('edit-btn-asset-audio'));

    await waitFor(() => {
      expect(screen.getByTestId('voice-recorder-asset-audio')).toBeInTheDocument();
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
      expect(screen.getByText(/No items found matching the current filters/)).toBeInTheDocument();
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
  it('shows spoken story indicator and remove audio button when audio_uri exists and drawer is open', async () => {
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
    });

    fireEvent.click(screen.getByTestId('edit-btn-asset-with-audio'));

    await waitFor(() => {
      expect(screen.getByTestId('delete-audio-btn-asset-with-audio')).toBeInTheDocument();
    });
  });

  // ── Image Editing Flow ─────────────────────────────────────────────────
  it('opens image editor and uploads edited image bytes', async () => {
    const mockAssets = [
      {
        id: 'asset-image-edit',
        title: 'Silver Bowl',
        description: 'A polished bowl',
        category: 'Other',
        valuation_min: 25,
        valuation_max: 50,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: 'static/uploads/primary.webp',
        images: [
          {
            id: 'image-primary',
            image_uri: 'static/uploads/primary.webp',
            is_primary: true,
            angle_label: 'Primary',
          },
        ],
      },
    ];

    let editedUpload = null;
    global.fetch.mockImplementation((url, options = {}) => {
      if (url.includes('/images/image-primary/replace') && options.method === 'POST') {
        editedUpload = options.body;
        return Promise.resolve({
          ok: true,
          json: async () => ({
            image_id: 'image-primary',
            image_uri: 'static/uploads/edited.webp',
            is_primary: true,
            angle_label: 'Primary',
          }),
        });
      }
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
      expect(screen.getByLabelText(/Edit Silver Bowl photo/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText(/Edit Silver Bowl photo/));

    await waitFor(() => {
      expect(screen.getByText('Edit Photo')).toBeInTheDocument();
      expect(screen.getByTestId('mock-image-cropper')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Brightness'), { target: { value: '125' } });
    expect(screen.getByTestId('mock-image-cropper')).toHaveAttribute(
      'data-filter',
      'brightness(125%) contrast(100%)',
    );

    fireEvent.click(screen.getByText('Save Edited Photo'));

    await waitFor(() => {
      expect(editedUpload).toBeInstanceOf(FormData);
    });
  });

  // ── Category Manager & AI Generation tests ──────────────────────────────
  describe('Category Manager, AI Details & Tags', () => {
    beforeEach(() => {
      global.__TEST_ENABLE_CATEGORIES_FETCH__ = true;
    });

    afterEach(() => {
      global.__TEST_ENABLE_CATEGORIES_FETCH__ = false;
    });

    it('renders Category Manager and allows adding a new category', async () => {
      let categoriesList = ['Jewelry', 'Furniture', 'Art', 'Other'];
      let postBody = null;

      global.fetch.mockImplementation((url, options) => {
        if (url.includes('/categories')) {
          if (options?.method === 'POST') {
            postBody = JSON.parse(options.body);
            categoriesList.push(postBody.name);
            return Promise.resolve({
              ok: true,
              json: async () => ({ status: 'success', category: postBody.name }),
            });
          }
          return Promise.resolve({
            ok: true,
            json: async () => categoriesList,
          });
        }
        if (url.includes('/assets') || url.includes('/heirs')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.reject(new Error('Unknown URL: ' + url));
      });

      render(<AdminInventoryDashboard sessionId={sessionId} />);

      // Open the category manager accordion
      await waitFor(() => {
        expect(screen.getByTestId('category-manager-toggle')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByTestId('category-manager-toggle'));

      // Wait for the category content to appear
      await waitFor(() => {
        expect(screen.getByTestId('new-category-input')).toBeInTheDocument();
      });

      const input = screen.getByTestId('new-category-input');
      fireEvent.change(input, { target: { value: 'Books' } });

      // Find the form and submit it directly (jsdom sometimes doesn't propagate button click → form submit)
      await waitFor(() => {
        expect(screen.getByTestId('add-category-btn')).not.toBeDisabled();
      });
      const formElement = document.querySelector('.category-manager-content form');
      fireEvent.submit(formElement);

      await waitFor(() => {
        expect(postBody).toEqual({ name: 'Books' });
      }, { timeout: 3000 });
      // Verify "Books" appears in the category accordion (use getAllByText since it may appear in filter dropdown too)
      const bookElements = screen.getAllByText('Books');
      expect(bookElements.length).toBeGreaterThanOrEqual(1);
    });

    it('allows deleting a category from Category Manager', async () => {
      let categoriesList = ['Jewelry', 'Furniture', 'Art', 'Other', 'Books'];
      let deletedName = null;
      window.confirm = vi.fn(() => true);

      global.fetch.mockImplementation((url, options) => {
        if (url.includes('/categories')) {
          if (options?.method === 'DELETE') {
            const parts = url.split('/');
            deletedName = decodeURIComponent(parts[parts.length - 1]);
            categoriesList = categoriesList.filter(c => c !== deletedName);
            return Promise.resolve({
              ok: true,
              json: async () => ({ status: 'success' }),
            });
          }
          return Promise.resolve({
            ok: true,
            json: async () => categoriesList,
          });
        }
        if (url.includes('/assets') || url.includes('/heirs')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<AdminInventoryDashboard sessionId={sessionId} />);

      // Open the category manager accordion
      await waitFor(() => {
        expect(screen.getByTestId('category-manager-toggle')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByTestId('category-manager-toggle'));

      await waitFor(() => {
        expect(screen.getByTestId('delete-category-Books')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('delete-category-Books'));

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalled();
        expect(deletedName).toBe('Books');
        expect(screen.queryByTestId('delete-category-Books')).not.toBeInTheDocument();
      });
    });

    it('calls AI details generator endpoint and fills form', async () => {
      const mockAssets = [{
        id: 'asset-ai',
        title: 'Old Painting',
        description: '',
        category: 'Art',
        valuation_min: 100,
        valuation_max: 200,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
      }];

      global.fetch.mockImplementation((url, options) => {
        if (url.includes('/generate-details')) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ title: 'AI Suggested Title', description: 'AI Suggested Description' }),
          });
        }
        if (url.includes('/categories')) {
          return Promise.resolve({ ok: true, json: async () => ['Jewelry', 'Furniture', 'Art', 'Other'] });
        }
        if (url.includes('/assets')) {
          return Promise.resolve({ ok: true, json: async () => mockAssets });
        }
        if (url.includes('/heirs')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.reject(new Error('Unknown URL: ' + url));
      });

      render(<AdminInventoryDashboard sessionId={sessionId} />);

      await waitFor(() => {
        expect(screen.getByTestId('edit-btn-asset-ai')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('edit-btn-asset-ai'));

      await waitFor(() => {
        expect(screen.getByTestId('generate-ai-btn-asset-ai')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('generate-ai-btn-asset-ai'));

      await waitFor(() => {
        expect(screen.getByTestId('edit-title-asset-ai').value).toBe('AI Suggested Title');
        expect(screen.getByTestId('edit-description-asset-ai').value).toBe('AI Suggested Description');
      });
    });

    it('supports quick tag suggestion clicks when editing', async () => {
      const mockAssets = [{
        id: 'asset-tag',
        title: 'Chest',
        description: '',
        category: 'Furniture',
        valuation_min: 100,
        valuation_max: 200,
        valuation_source: 'Personal Estimate',
        status: 'STAGED',
        ocr_status: 'COMPLETED',
        image_uri: null,
        sentiment_tag: '',
      }];

      global.fetch.mockImplementation((url) => {
        if (url.includes('/categories')) {
          return Promise.resolve({ ok: true, json: async () => ['Jewelry', 'Furniture', 'Art', 'Other'] });
        }
        if (url.includes('/assets')) {
          return Promise.resolve({ ok: true, json: async () => mockAssets });
        }
        if (url.includes('/heirs')) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.reject(new Error('Unknown URL'));
      });

      render(<AdminInventoryDashboard sessionId={sessionId} />);

      await waitFor(() => {
        expect(screen.getByTestId('edit-btn-asset-tag')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTestId('edit-btn-asset-tag'));

      await waitFor(() => {
        expect(screen.getByTestId('suggested-tag-Heirloom')).toBeInTheDocument();
      });

      // Click Heirloom suggestion to add it
      fireEvent.click(screen.getByTestId('suggested-tag-Heirloom'));
      expect(screen.getByTestId('edit-sentiment-asset-tag').value).toBe('Heirloom');

      // Click Memento suggestion to append it
      fireEvent.click(screen.getByTestId('suggested-tag-Memento'));
      expect(screen.getByTestId('edit-sentiment-asset-tag').value).toBe('Heirloom, Memento');

      // Click Heirloom suggestion again to remove it
      fireEvent.click(screen.getByTestId('suggested-tag-Heirloom'));
      expect(screen.getByTestId('edit-sentiment-asset-tag').value).toBe('Memento');
    });
  });
});
