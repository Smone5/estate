import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import { customConfirm, customPrompt } from '../store/useDialogStore';
import AssetGallery from './AssetGallery';
import AdminVoiceRecorder from './AdminVoiceRecorder';
import ImageEditModal from './ImageEditModal';
import {
  getDisplayDescription,
  getStructuredAssetDetails,
  hasStructuredAssetDetails,
  StructuredAssetDetails,
} from '../utils/assetDetails';
import {
  saveStagingItem,
  loadStagingItems,
  loadPendingStagingItems,
  deleteStagingItem,
  updateStagingItemStatus,
} from '../utils/stagingDB';
import { autoCompress } from '../utils/imageCompression';

const LEGAL_NOTICE = 'This system is strictly for personal property and keepsakes. Do not upload real estate, vehicles, or bank/financial accounts.';

// Default categories used for fallback/initialization
const CATEGORIES = ['Jewelry', 'Furniture', 'Art', 'Other'];

const VALUATION_SOURCES = [
  'Professional Appraisal',
  'Tax Assessment',
  'Estate Sale Estimator',
  'Personal Estimate',
  'AI Appraisal',
];

const DIMENSION_CONFIDENCE_OPTIONS = ['', 'Low', 'Medium', 'High'];

const EDIT_DETAIL_TABS = [
  { id: 'basics', label: 'Title' },
  { id: 'specifications', label: 'Specifications' },
  { id: 'condition', label: 'Condition' },
  { id: 'dimensions', label: 'Dimensions' },
  { id: 'estimate', label: 'Estimate' },
  { id: 'search', label: 'Search' },
  { id: 'images', label: 'Images' },
];

// Default room/location options
const DEFAULT_ROOMS = [
  'Living Room',
  'Kitchen',
  'Dining Room',
  'Master Bedroom',
  'Guest Bedroom',
  'Bathroom',
  'Home Office',
  'Basement',
  'Attic',
  'Garage',
  'Yard / Garden',
];

const ROOM_STORAGE_KEY = 'estate_steward_staging_room';
const STATUS_MESSAGES = [
  'Analyzing image composition...',
  'Extracting visual characteristics...',
  'Identifying materials and era...',
  'Generating title suggestions...',
  'Drafting short item overview...',
  'Composing detailed specifications...',
  'Writing condition report and wear details...',
  'Compiling search keywords...',
  'Calibrating secondary market valuation...',
  'Selecting relevant sentiment tags...',
  'Saving to database & updating index...'
];

const MAX_STAGING_PHOTOS = 12;
const STAGING_UPLOAD_TIMEOUT_MS = 45_000;
const INVENTORY_REFRESH_TIMEOUT_MS = 15_000;
const OCR_POLL_INTERVAL_MS = 5_000;
const MAX_OCR_POLL_ATTEMPTS = 12;
const PHOTO_LABEL_SUGGESTIONS = [
  'Front',
  'Back',
  'Maker / brand mark',
  'Damage / wear',
  'Size reference',
  'Close-up detail',
];

/**
 * Retrieve the persisted room selection from localStorage, or default to 'Living Room'.
 */
function getPersistedRoom() {
  try {
    const stored = localStorage.getItem(ROOM_STORAGE_KEY);
    if (stored && stored.trim().length > 0) return stored.trim();
  } catch { /* ignore */ }
  return 'Living Room';
}

function getAudioFilename(blob) {
  const mimeType = blob?.type?.toLowerCase() || '';
  if (mimeType.includes('mp4') || mimeType.includes('m4a') || mimeType.includes('aac')) {
    return 'recording.m4a';
  }
  if (mimeType.includes('ogg')) return 'recording.ogg';
  if (mimeType.includes('wav')) return 'recording.wav';
  return 'recording.webm';
}

function normalizeMediaSrc(src) {
  if (!src) return '';
  if (/^(https?:|data:|blob:)/i.test(src)) return src;
  return src.startsWith('/') ? src : `/${src}`;
}

function normalizeOptionalNumberInput(value) {
  if (value === '' || value == null) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 ? numeric : null;
}

async function fetchWithTimeout(url, options, timeoutMs = STAGING_UPLOAD_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new Error('Upload timed out. The item is saved locally and will retry automatically.');
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export default function AdminInventoryDashboard({
  sessionId,
  assets: propAssets,
  heirs: propHeirs,
  onRefreshAssets,
  onRefreshHeirs,
}) {
  const store = useMediationStore();
  const sessionStatus = useMediationStore((s) => s.sessionStatus);

  const [internalAssets, setInternalAssets] = useState([]);
  const [internalHeirs, setInternalHeirs] = useState([]);
  const [loading, setLoading] = useState(propAssets === undefined);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [aiGenerationError, setAiGenerationError] = useState(null);
  const [editingAssetId, setEditingAssetId] = useState(null);

  // Redesign states
  const [isCategoryManagerOpen, setIsCategoryManagerOpen] = useState(false);
  const [isQuickCaptureOpen, setIsQuickCaptureOpen] = useState(false);
  const [isFilterBarOpen, setIsFilterBarOpen] = useState(true);
  const [viewMode, setViewMode] = useState('grid');
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('All');
  const [filterStatus, setFilterStatus] = useState('All');
  const [sortOption, setSortOption] = useState('id_desc');
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);

  const assets = propAssets !== undefined ? propAssets : internalAssets;
  const heirs = propHeirs !== undefined ? propHeirs : internalHeirs;

  // ── Mobile Camera Hub States ──────────────────────────────────────────
  const [stagingRoom, setStagingRoom] = useState(getPersistedRoom);
  const [customRoom, setCustomRoom] = useState('');
  const [showCustomRoomInput, setShowCustomRoomInput] = useState(false);
  const [stagingPhotos, setStagingPhotos] = useState([]);
  const [editingStagingPhotoId, setEditingStagingPhotoId] = useState(null);
  const [autoDescribeImages, setAutoDescribeImages] = useState(true);
  const [audioBlob, setAudioBlob] = useState(null);
  const [stageSuccess, setStageSuccess] = useState(null); // { asset_id, title }
  const [isStaging, setIsStaging] = useState(false);
  const [stagingStatus, setStagingStatus] = useState('');
  const [uploadQueue, setUploadQueue] = useState([]); // items from IndexedDB pending upload
  const [uploadingIndexed, setUploadingIndexed] = useState(null); // asset_id currently uploading
  const stagingFileInputRef = useRef(null);
  const cameraCaptureInputRef = useRef(null);
  const [showPhotoLabelHelp, setShowPhotoLabelHelp] = useState(false);

  // Edit form state
  const [activeEditTab, setActiveEditTab] = useState('basics');
  const [editForm, setEditForm] = useState({
    title: '',
    description: '',
    category: 'Other',
    valuation_min: 0,
    valuation_max: 0,
    valuation_source: 'Personal Estimate',
    length_in: '',
    width_in: '',
    height_in: '',
    weight_lb: '',
    dimension_source: '',
    dimension_confidence: '',
    dimension_notes: '',
    sentiment_tag: '',
  });

  // Pre-allocation state
  const [preAllocatingAssetId, setPreAllocatingAssetId] = useState(null);
  const [selectedHeirId, setSelectedHeirId] = useState('');

  // Audio upload state
  const [audioAssetId, setAudioAssetId] = useState(null);

  // Secondary images upload state
  const [secondaryUploading, setSecondaryUploading] = useState(false);
  const [secondaryAngleLabel, setSecondaryAngleLabel] = useState('');
  const [secondaryFile, setSecondaryFile] = useState(null);
  const [secondaryError, setSecondaryError] = useState(null);
  const [editingImage, setEditingImage] = useState(null);
  const [imageEditSaving, setImageEditSaving] = useState(false);
  const [previewAsset, setPreviewAsset] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteReason, setDeleteReason] = useState('');
  const [deleteError, setDeleteError] = useState(null);
  const [deletingAsset, setDeletingAsset] = useState(false);
  const [expandedDescriptionIds, setExpandedDescriptionIds] = useState(() => new Set());
  const hasLoadedAssetsRef = useRef(propAssets !== undefined);
  const assetFetchInFlightRef = useRef(false);
  const ocrPollAttemptsRef = useRef(0);
  const processingAssetKeyRef = useRef('');

  // Category manager states
  const [categories, setCategories] = useState(CATEGORIES);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [categoryCreating, setCategoryCreating] = useState(false);

  // AI Details generation state
  const [generatingDetails, setGeneratingDetails] = useState({});
  const [aiGeneratedAssets, setAiGeneratedAssets] = useState({});
  const [verifyingAssets, setVerifyingAssets] = useState({});
  const [loaderMessage, setLoaderMessage] = useState('');
  
  // AI Feedback states
  const [feedbackRating, setFeedbackRating] = useState(null); // 'thumbs_up' | 'thumbs_down' | null
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [showFeedbackCommentField, setShowFeedbackCommentField] = useState(false);

  // Pending batch updates
  const [pendingUpdatesCount, setPendingUpdatesCount] = useState(0);
  const [publishingUpdates, setPublishingUpdates] = useState(false);

  const toggleDescriptionExpanded = (assetId) => {
    setExpandedDescriptionIds((current) => {
      const next = new Set(current);
      if (next.has(assetId)) {
        next.delete(assetId);
      } else {
        next.add(assetId);
      }
      return next;
    });
  };

  const fetchCategories = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`/api/sessions/${sessionId}/categories`, {
        credentials: 'same-origin',
      });
      if (res && res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.every(item => typeof item === 'string')) {
          setCategories(data);
        }
      }
    } catch (err) {
      console.error('Failed to fetch categories', err);
    }
  }, [sessionId]);

  useEffect(() => {
    const isTest = typeof process !== 'undefined' && process.env.NODE_ENV === 'test';
    if (isTest && !global.__TEST_ENABLE_CATEGORIES_FETCH__) {
      return;
    }
    fetchCategories();
  }, [fetchCategories]);

  async function handleCreateCategory(e) {
    e.preventDefault();
    const name = newCategoryName.trim();
    if (!name) return;
    setCategoryCreating(true);
    setError(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/categories`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to create category: ${res.status}`);
      }
      setNewCategoryName('');
      await fetchCategories();
    } catch (err) {
      setError(err.message);
    } finally {
      setCategoryCreating(false);
    }
  }

  async function handleDeleteCategory(name) {
    if (!await customConfirm(`Are you sure you want to delete the category "${name}"?`)) {
      return;
    }
    setError(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/categories/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to delete category: ${res.status}`);
      }
      await fetchCategories();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleGenerateDetails(assetId) {
    setGeneratingDetails((prev) => ({ ...prev, [assetId]: true }));
    setError(null);
    try {
      const res = await fetch(`/api/assets/${assetId}/generate-details`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `AI Generation failed: ${res.status}`);
      }
      const data = await res.json();
      setAiGeneratedAssets((prev) => ({ ...prev, [assetId]: true }));
      setAiGenerationError(null);
      setEditForm((prev) => ({
        ...prev,
        title: data.title || prev.title,
        category: data.category || prev.category,
        description: data.item_overview || data.description || prev.description,
        item_overview: data.item_overview || prev.item_overview || '',
        specifications: data.specifications || prev.specifications || '',
        condition_report: data.condition_report || prev.condition_report || '',
        keywords: data.keywords || prev.keywords || '',
        valuation_min: data.valuation_min ?? prev.valuation_min,
        valuation_max: data.valuation_max ?? prev.valuation_max,
        valuation_source: data.valuation_source || 'AI Appraisal',
        length_in: data.length_in ?? prev.length_in ?? '',
        width_in: data.width_in ?? prev.width_in ?? '',
        height_in: data.height_in ?? prev.height_in ?? '',
        weight_lb: data.weight_lb ?? prev.weight_lb ?? '',
        dimension_source: data.dimension_source || prev.dimension_source || '',
        dimension_confidence: data.dimension_confidence || prev.dimension_confidence || '',
        dimension_notes: data.dimension_notes || prev.dimension_notes || '',
        sentiment_tag: data.sentiment_tags || prev.sentiment_tag,
      }));
    } catch (err) {
      setAiGenerationError(err.message);
    } finally {
      setGeneratingDetails((prev) => ({ ...prev, [assetId]: false }));
    }
  }

  async function handleVerifyAsset(assetId) {
    setVerifyingAssets((prev) => ({ ...prev, [assetId]: true }));
    try {
      const res = await fetch(`/api/assets/${assetId}/ai-feedback`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: 'thumbs_up', comment: 'Human verified after AI generation' }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to save verification: ${res.status}`);
      }
      // Mark as verified in local state and clear the "just generated" banner
      setAiGeneratedAssets((prev) => ({ ...prev, [assetId]: false }));
      setAssets((prev) => prev.map((a) => a.id === assetId ? { ...a, ai_feedback: JSON.stringify({ rating: 'thumbs_up' }) } : a));
    } catch (err) {
      setError(err.message);
    } finally {
      setVerifyingAssets((prev) => ({ ...prev, [assetId]: false }));
    }
  }

  function getCategoryColor(category) {
    const colors = {
      Jewelry: '#C29F53',
      Furniture: '#8E7558',
      Art: '#7E6C84',
      Other: '#64748B',
    };
    if (colors[category]) return colors[category];
    let hash = 0;
    for (let i = 0; i < category.length; i++) {
      hash = category.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash % 360);
    return `hsl(${hue}, 40%, 45%)`;
  }

  async function handleSecondaryUpload(assetId) {
    if (!secondaryFile) {
      setSecondaryError('Please select a file to upload.');
      return;
    }

    setSecondaryUploading(true);
    setSecondaryError(null);

    try {
      const formData = new FormData();
      formData.append('file', secondaryFile);
      if (secondaryAngleLabel.trim()) {
        formData.append('angle_label', secondaryAngleLabel.trim());
      }

      const res = await fetch(`/api/assets/${assetId}/images`, {
        method: 'POST',
        credentials: 'same-origin',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Upload failed: ${res.status}`);
      }

      setSecondaryFile(null);
      setSecondaryAngleLabel('');
      await fetchAssets();
    } catch (err) {
      setSecondaryError(err.message);
    } finally {
      setSecondaryUploading(false);
    }
  }

  async function handleSecondaryDelete(assetId, imageId) {
    if (!await customConfirm('Are you sure you want to delete this secondary view?')) {
      return;
    }

    setSecondaryError(null);
    try {
      const res = await fetch(`/api/assets/${assetId}/images/${imageId}`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Delete failed: ${res.status}`);
      }

      await fetchAssets();
    } catch (err) {
      setSecondaryError(err.message);
    }
  }

  async function handleSaveEditedImage(blob) {
    if (!editingImage) return;

    setImageEditSaving(true);
    setSecondaryError(null);
    try {
      const formData = new FormData();
      formData.append('file', blob, 'edited-photo.webp');

      const res = await fetch(`/api/assets/${editingImage.assetId}/images/${editingImage.image.id}/replace`, {
        method: 'POST',
        credentials: 'same-origin',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Image edit failed: ${res.status}`);
      }

      setEditingImage(null);
      await fetchAssets();
    } catch (err) {
      setSecondaryError(err.message);
      throw err;
    } finally {
      setImageEditSaving(false);
    }
  }

  const isSetupOrActive = sessionStatus === 'SETUP' || sessionStatus === 'ACTIVE';

  // ── Fetch assets and heirs ──────────────────────────────────────────────
  const fetchAssets = useCallback(async () => {
    if (!sessionId) return;
    if (assetFetchInFlightRef.current) return;
    assetFetchInFlightRef.current = true;
    if (onRefreshAssets) {
      try {
        await onRefreshAssets();
        try {
          const pRes = await fetch(`/api/sessions/${sessionId}/pending-updates`, {
            credentials: 'same-origin',
          });
          if (pRes && pRes.ok) {
            const pData = await pRes.json();
            setPendingUpdatesCount(pData.pending_count || 0);
          }
        } catch (e) {
          // Pending update count is supplementary.
        }
      } finally {
        assetFetchInFlightRef.current = false;
      }
      return;
    }
    try {
      if (!hasLoadedAssetsRef.current) {
        setLoading(true);
      }
      const res = await fetchWithTimeout(`/api/sessions/${sessionId}/assets`, {
        credentials: 'same-origin',
      }, INVENTORY_REFRESH_TIMEOUT_MS);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Inventory refresh failed: ${res.status}`);
      }
      const data = await res.json();
      setInternalAssets(Array.isArray(data) ? data : data.assets || []);
      hasLoadedAssetsRef.current = true;
      try {
        const pRes = await fetch(`/api/sessions/${sessionId}/pending-updates`, {
          credentials: 'same-origin',
        });
        if (pRes && pRes.ok) {
          const pData = await pRes.json();
          setPendingUpdatesCount(pData.pending_count || 0);
        }
      } catch (e) {}
    } catch (err) {
      console.error('Failed to fetch assets', err);
      setError(
        hasLoadedAssetsRef.current
          ? `The item was staged, but the inventory refresh is taking longer than expected. ${err.message}`
          : `Failed to load assets. ${err.message}`
      );
    } finally {
      setLoading(false);
      assetFetchInFlightRef.current = false;
    }
  }, [sessionId, onRefreshAssets]);

  async function handlePublishUpdates() {
    if (pendingUpdatesCount === 0) return;
    if (!await customConfirm(`Are you sure you want to publish all ${pendingUpdatesCount} pending updates to beneficiaries? This will send them email notifications and update their dashboards.`)) {
      return;
    }
    setPublishingUpdates(true);
    setError(null);
    try {
      const res = await fetch(`/api/sessions/${sessionId}/publish-updates`, {
        method: 'POST',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Publish updates failed: ${res.status}`);
      }
      await fetchAssets();
    } catch (err) {
      setError(err.message);
    } finally {
      setPublishingUpdates(false);
    }
  }

  const fetchHeirs = useCallback(async () => {
    if (!sessionId) return;
    if (onRefreshHeirs) {
      await onRefreshHeirs();
      return;
    }
    try {
      const res = await fetch(`/api/sessions/${sessionId}/heirs`, {
        credentials: 'same-origin',
      });
      if (res.ok) {
        const data = await res.json();
        setInternalHeirs(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to fetch heirs', err);
    }
  }, [sessionId, onRefreshHeirs]);

  useEffect(() => {
    if (propAssets === undefined) {
      fetchAssets();
    }
    if (propHeirs === undefined) {
      fetchHeirs();
    }
  }, [fetchAssets, fetchHeirs, propAssets, propHeirs]);

  // Poll for OCR status updates on PROCESSING assets
  useEffect(() => {
    const processingAssetKey = assets
      .filter((asset) => asset.ocr_status === 'PROCESSING')
      .map((asset) => asset.id)
      .sort()
      .join(',');

    if (!processingAssetKey) {
      processingAssetKeyRef.current = '';
      ocrPollAttemptsRef.current = 0;
      return;
    }

    if (processingAssetKeyRef.current !== processingAssetKey) {
      processingAssetKeyRef.current = processingAssetKey;
      ocrPollAttemptsRef.current = 0;
    }

    const interval = setInterval(() => {
      if (ocrPollAttemptsRef.current >= MAX_OCR_POLL_ATTEMPTS) {
        clearInterval(interval);
        return;
      }
      ocrPollAttemptsRef.current += 1;
      fetchAssets();
    }, OCR_POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [assets, fetchAssets]);

  // ── Room Selector ────────────────────────────────────────────────────────
  function handleRoomChange(newRoom) {
    if (newRoom === '__custom__') {
      setShowCustomRoomInput(true);
      setCustomRoom('');
      return;
    }
    setStagingRoom(newRoom);
    setShowCustomRoomInput(false);
    try {
      localStorage.setItem(ROOM_STORAGE_KEY, newRoom);
    } catch { /* ignore */ }
  }

  function handleCustomRoomSubmit() {
    const trimmed = customRoom.trim();
    if (!trimmed) return;
    setStagingRoom(trimmed);
    setShowCustomRoomInput(false);
    setCustomRoom('');
    try {
      localStorage.setItem(ROOM_STORAGE_KEY, trimmed);
    } catch { /* ignore */ }
  }

  // ── Quick Capture Photo Stack ───────────────────────────────────────────
  async function addFilesToStaging(files) {
    const availableSlots = MAX_STAGING_PHOTOS - stagingPhotos.length;
    const selectedFiles = Array.from(files || []);

    if (selectedFiles.length === 0) return;
    if (selectedFiles.length > availableSlots) {
      setError(`You can add ${availableSlots} more photo${availableSlots === 1 ? '' : 's'} to this item.`);
      return;
    }

    const invalidFile = selectedFiles.find((file) => !file.type?.startsWith('image/'));
    if (invalidFile) {
      setError(`"${invalidFile.name}" is not a supported image file.`);
      return;
    }

    const oversizedFile = selectedFiles.find((file) => file.size > 10 * 1024 * 1024);
    if (oversizedFile) {
      setError(`Image "${oversizedFile.name}" must be under 10MB.`);
      return;
    }

    setError(null);

    try {
      const preparedPhotos = [];
      for (const file of selectedFiles) {
        const { blob: compressedBlob } = await autoCompress(file, 2048, 0.85);
        preparedPhotos.push({
          id: crypto.randomUUID
            ? crypto.randomUUID()
            : `photo-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          blob: compressedBlob,
          previewUrl: URL.createObjectURL(compressedBlob),
          originalName: file.name || 'capture.webp',
          label: '',
        });
      }

      setStagingPhotos((prev) => [
        ...prev,
        ...preparedPhotos.map((photo, index) => ({
          ...photo,
          label: prev.length === 0 && index === 0 ? 'Front' : photo.label,
        })),
      ]);

      if (navigator.vibrate) {
        navigator.vibrate([50, 50]);
      }
    } catch (err) {
      console.error('Failed to process image:', err);
      setError('Failed to process image. Please try another file.');
    }
  }

  async function handleStagingFileUpload(e) {
    await addFilesToStaging(e.target.files);
    e.target.value = '';
  }

  function triggerCameraCapture() {
    if (stagingPhotos.length >= MAX_STAGING_PHOTOS) {
      setError(`You can add up to ${MAX_STAGING_PHOTOS} photos for one item.`);
      return;
    }
    // Delegate to the OS camera via a capture-attributed file input.
    // getUserMedia-based custom overlays are unreliable in installed
    // (standalone-display) PWAs on iOS/Android, where camera permission
    // prompts can silently fail to appear.
    cameraCaptureInputRef.current?.click();
  }

  async function handleCameraCaptureChange(e) {
    await addFilesToStaging(e.target.files);
    e.target.value = '';
  }

  function removeStagingPhoto(photoId) {
    setStagingPhotos((prev) => {
      const photo = prev.find((item) => item.id === photoId);
      if (photo?.previewUrl) {
        URL.revokeObjectURL(photo.previewUrl);
      }
      return prev.filter((item) => item.id !== photoId);
    });
  }

  function updateStagingPhotoLabel(photoId, label) {
    setStagingPhotos((prev) => prev.map((photo) => (
      photo.id === photoId ? { ...photo, label } : photo
    )));
  }

  function setPrimaryStagingPhoto(photoId) {
    setStagingPhotos((prev) => {
      const selected = prev.find((photo) => photo.id === photoId);
      if (!selected) return prev;
      return [selected, ...prev.filter((photo) => photo.id !== photoId)];
    });
  }

  function clearStagingPhotos() {
    stagingPhotos.forEach((photo) => {
      if (photo.previewUrl) URL.revokeObjectURL(photo.previewUrl);
    });
    setStagingPhotos([]);
  }

  async function handleSaveEditedStagingPhoto(blob) {
    const photoId = editingStagingPhotoId;
    if (!photoId) return;

    const previewUrl = URL.createObjectURL(blob);
    setStagingPhotos((prev) => prev.map((photo) => {
      if (photo.id !== photoId) return photo;
      if (photo.previewUrl) URL.revokeObjectURL(photo.previewUrl);
      return {
        ...photo,
        blob,
        previewUrl,
        originalName: 'edited-capture.webp',
      };
    }));
    setEditingStagingPhotoId(null);
  }

  // ── Audio Recording for Staging ──────────────────────────────────────────
  function handleRecordingSaved(blob) {
    setAudioBlob(blob);
    if (navigator.vibrate) {
      navigator.vibrate([50, 50]);
    }
  }

  function clearAudio() {
    setAudioBlob(null);
  }

  // ── Stage Photo Stack ────────────────────────────────────────────────────
  async function handleStageFromSlots() {
    if (stagingPhotos.length === 0) {
      setError('Capture at least one photo before staging.');
      return;
    }
    if (!isSetupOrActive) {
      setError('Assets can only be staged during the Setup or Active phase.');
      return;
    }

    setIsStaging(true);
    setStagingStatus('Saving locally...');
    setError(null);

    try {
      // Generate client-side UUID
      const assetId = crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
      });

      const primaryPhoto = stagingPhotos[0];
      const secondaryPhotos = stagingPhotos.slice(1);

      // First, save everything to IndexedDB for offline resilience
      await saveStagingItem({
        asset_id: assetId,
        session_id: sessionId,
        location: stagingRoom,
        photos: stagingPhotos.map((photo, idx) => ({
          blob: photo.blob,
          label: photo.label || (idx === 0 ? 'Primary' : `View ${idx + 1}`),
          is_primary: idx === 0,
        })),
        primary_blob: primaryPhoto?.blob || null,
        secondary_blobs: secondaryPhotos.map((photo) => photo.blob),
        audio_blob: audioBlob || null,
        auto_appraise: autoDescribeImages,
        upload_status: 'pending',
      });

      // Attempt immediate upload
      setStagingStatus('Uploading photos and audio...');
      const formData = new FormData();
      formData.append('asset_id', assetId);
      formData.append('location', stagingRoom);
      formData.append('auto_appraise', autoDescribeImages ? 'true' : 'false');
      formData.append('angle_labels', JSON.stringify(
        stagingPhotos.map((photo, idx) => photo.label || (idx === 0 ? 'Primary' : `View ${idx + 1}`))
      ));

      stagingPhotos.forEach((photo, idx) => {
        const name = idx === 0 ? 'primary.webp' : `view_${idx + 1}.webp`;
        formData.append('files', photo.blob, name);
      });

      if (audioBlob) {
        formData.append('audio', audioBlob, getAudioFilename(audioBlob));
      }

      const res = await fetchWithTimeout(`/api/sessions/${sessionId}/assets/stage`, {
        method: 'POST',
        credentials: 'same-origin',
        body: formData,
      });

      if (!res.ok) {
        // Server upload failed — item stays in IndexedDB as pending for background retry
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Upload failed: ${res.status}`);
      }

      const data = await res.json();

      // The server confirmed persistence, so the offline copy is no longer needed.
      setStagingStatus('Finalizing...');
      await deleteStagingItem(assetId);

      // Clear staging photos
      clearStagingPhotos();
      setAudioBlob(null);

      // Show success
      setStageSuccess({ asset_id: data.asset_id });
      if (navigator.vibrate) {
        navigator.vibrate([50, 50]);
      }

      // Refresh assets list
      await fetchAssets();

      // Clear success message after 3s
      setTimeout(() => setStageSuccess(null), 3000);
    } catch (err) {
      // If immediate upload fails, item remains in IndexedDB for background retry
      console.warn('Staging upload failed (queued in IndexedDB):', err.message);
      setError(`Staged locally — will retry upload automatically. ${err.message}`);

      // Clear photo stack anyway so the user can keep capturing the next item.
      clearStagingPhotos();
      setAudioBlob(null);

      if (navigator.vibrate) {
        navigator.vibrate([50, 50]);
      }

      // Refresh upload queue
      loadUploadQueue();
    } finally {
      setIsStaging(false);
      setStagingStatus('');
    }
  }

  // ── Background Upload Queue ─────────────────────────────────────────────
  const loadUploadQueue = useCallback(async () => {
    try {
      const pending = await loadPendingStagingItems();
      setUploadQueue(pending);
    } catch (err) {
      console.warn('Failed to load upload queue:', err);
    }
  }, []);

  useEffect(() => {
    loadUploadQueue();
  }, [loadUploadQueue]);

  // Background upload processor — runs sequentially
  const uploadQueueRef = useRef(uploadQueue);
  uploadQueueRef.current = uploadQueue;

  const uploadingRef = useRef(false);

  const processUploadQueue = useCallback(async () => {
    if (uploadingRef.current) return;
    if (uploadQueueRef.current.length === 0) return;

    uploadingRef.current = true;
    const item = uploadQueueRef.current[0];

    try {
      setUploadingIndexed(item.asset_id);
      await updateStagingItemStatus(item.asset_id, 'uploading');

      const formData = new FormData();
      formData.append('asset_id', item.asset_id);
      formData.append('location', item.location || 'Unknown');
      formData.append('auto_appraise', item.auto_appraise === false ? 'false' : 'true');

      const queuedPhotos = item.photos?.length
        ? item.photos
        : [
            item.primary_blob ? { blob: item.primary_blob, label: 'Primary' } : null,
            ...(item.secondary_blobs || []).map((blob, idx) => ({ blob, label: `View ${idx + 2}` })),
          ].filter(Boolean);

      formData.append('angle_labels', JSON.stringify(
        queuedPhotos.map((photo, idx) => photo.label || (idx === 0 ? 'Primary' : `View ${idx + 1}`))
      ));

      queuedPhotos.forEach((photo, idx) => {
        if (photo?.blob) {
          formData.append('files', photo.blob, idx === 0 ? 'primary.webp' : `view_${idx + 1}.webp`);
        }
      });

      if (item.audio_blob) {
        formData.append('audio', item.audio_blob, getAudioFilename(item.audio_blob));
      }

      const res = await fetchWithTimeout(`/api/sessions/${item.session_id}/assets/stage`, {
        method: 'POST',
        credentials: 'same-origin',
        body: formData,
      });

      if (!res.ok) {
        // Mark as failed but keep for retry
        await updateStagingItemStatus(item.asset_id, 'failed');
        throw new Error(`Upload returned ${res.status}`);
      }

      // Success — remove from IndexedDB queue
      await deleteStagingItem(item.asset_id);
      await fetchAssets();
    } catch (err) {
      console.warn('Background upload failed for', item.asset_id, ':', err.message);
    } finally {
      setUploadingIndexed(null);
      uploadingRef.current = false;
      await loadUploadQueue();
    }
  }, [fetchAssets, loadUploadQueue]);

  // Auto-process queue every 5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      processUploadQueue();
    }, 5000);

    // Also process immediately on mount
    processUploadQueue();

    return () => clearInterval(interval);
  }, [processUploadQueue]);

  // ── File Upload / Stage (original desktop flow preserved) ────────────────
  async function handleFileUpload(e) {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    if (files.length > 10) {
      setError('You can upload a maximum of 10 images at once.');
      return;
    }

    for (const file of files) {
      const lowerName = file.name.toLowerCase();
      const isImage = file.type.startsWith('image/') ||
        ['.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif', '.bmp', '.tiff', '.gif']
          .some((ext) => lowerName.endsWith(ext));
      if (!isImage) {
        setError(`Only image files are accepted (JPG, PNG, WebP, HEIC, TIFF, BMP, GIF). File "${file.name}" is invalid.`);
        return;
      }

      if (file.size > 10 * 1024 * 1024) {
        setError(`Image "${file.name}" must be under 10MB.`);
        return;
      }
    }

    setError(null);
    setUploading(true);

    try {
      const formData = new FormData();
      files.forEach((file) => {
        formData.append('files', file);
      });

      const res = await fetch(`/api/sessions/${sessionId}/assets/stage`, {
        method: 'POST',
        credentials: 'same-origin',
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Upload failed: ${res.status}`);
      }

      await fetchAssets();
      e.target.value = ''; // Reset file input
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  }

  // ── Edit Metadata ───────────────────────────────────────────────────────
  function startEditing(asset) {
    // Parse description_json for AI-generated structured fields
    let djson = {};
    try {
      if (asset.description_json) {
        djson = typeof asset.description_json === 'string'
          ? JSON.parse(asset.description_json)
          : asset.description_json;
      }
    } catch (e) { /* ignore */ }

    setEditingAssetId(asset.id);
    setActiveEditTab('basics');
    setEditForm({
      title: asset.title || '',
      description: asset.description || '',
      category: asset.category || 'Other',
      valuation_min: asset.valuation_min ?? 0,
      valuation_max: asset.valuation_max ?? 0,
      valuation_source: asset.valuation_source || 'Personal Estimate',
      length_in: asset.length_in ?? djson.dimensions?.length_in ?? '',
      width_in: asset.width_in ?? djson.dimensions?.width_in ?? '',
      height_in: asset.height_in ?? djson.dimensions?.height_in ?? '',
      weight_lb: asset.weight_lb ?? djson.dimensions?.weight_lb ?? '',
      dimension_source: asset.dimension_source || djson.dimensions?.source || djson.dimensions?.dimension_source || '',
      dimension_confidence: asset.dimension_confidence || djson.dimensions?.confidence || djson.dimensions?.dimension_confidence || '',
      dimension_notes: asset.dimension_notes || djson.dimensions?.notes || djson.dimensions?.dimension_notes || '',
      sentiment_tag: asset.sentiment_tag || '',
      item_overview: djson.item_overview || '',
      specifications: djson.specifications || '',
      condition_report: djson.condition_report || '',
      keywords: djson.keywords || '',
    });
    setError(null);
    setSecondaryAngleLabel('');
    setSecondaryFile(null);
    setSecondaryError(null);
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
      const asset = assets.find((a) => a.id === assetId);
      const isMajor = sessionStatus === 'ACTIVE';
      let reason = null;

      if (isMajor) {
        reason = await customPrompt("A reason is required when publishing a new asset post-launch (during ACTIVE phase):");
        if (reason === null) return; // Cancelled
        if (!reason.trim()) {
          setError("A reason is required when publishing a new asset post-launch.");
          return;
        }
      }

      const assetData =
        editingAssetId === assetId
          ? {
              ...editForm,
              length_in: normalizeOptionalNumberInput(editForm.length_in),
              width_in: normalizeOptionalNumberInput(editForm.width_in),
              height_in: normalizeOptionalNumberInput(editForm.height_in),
              weight_lb: normalizeOptionalNumberInput(editForm.weight_lb),
              dimension_source: editForm.dimension_source || undefined,
              dimension_confidence: editForm.dimension_confidence || undefined,
              dimension_notes: editForm.dimension_notes || undefined,
              reason: reason || undefined,
            }
          : (() => {
              return {
                title: asset?.title || '',
                description: asset?.description || '',
                category: asset?.category || 'Other',
                valuation_min: asset?.valuation_min ?? 0,
                valuation_max: asset?.valuation_max ?? 0,
                valuation_source: asset?.valuation_source || 'Personal Estimate',
                length_in: asset?.length_in ?? null,
                width_in: asset?.width_in ?? null,
                height_in: asset?.height_in ?? null,
                weight_lb: asset?.weight_lb ?? null,
                dimension_source: asset?.dimension_source || undefined,
                dimension_confidence: asset?.dimension_confidence || undefined,
                dimension_notes: asset?.dimension_notes || undefined,
                sentiment_tag: asset?.sentiment_tag || '',
                reason: reason || undefined,
              };
            })();

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
        credentials: 'same-origin',
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

  async function handleSave(assetId) {
    setError(null);
    try {
      const originalAsset = assets.find((a) => a.id === assetId);
      const isTitleChanged = editForm.title !== originalAsset.title;
      const isValMinChanged = Number(editForm.valuation_min) !== Number(originalAsset.valuation_min);
      const isValMaxChanged = Number(editForm.valuation_max) !== Number(originalAsset.valuation_max);
      const isMajor = (isTitleChanged || isValMinChanged || isValMaxChanged) && (originalAsset.status === 'LIVE' && sessionStatus === 'ACTIVE');
      let reason = null;

      if (isMajor) {
        reason = await customPrompt("A reason for the change is required for major asset edits (value/title changes) post-launch:");
        if (reason === null) return; // Cancelled
        if (!reason.trim()) {
          setError("A reason is required to save major edits.");
          return;
        }
      }

      const payload = {
        ...editForm,
        length_in: normalizeOptionalNumberInput(editForm.length_in),
        width_in: normalizeOptionalNumberInput(editForm.width_in),
        height_in: normalizeOptionalNumberInput(editForm.height_in),
        weight_lb: normalizeOptionalNumberInput(editForm.weight_lb),
        dimension_source: editForm.dimension_source || null,
        dimension_confidence: editForm.dimension_confidence || null,
        dimension_notes: editForm.dimension_notes || null,
        reason: reason || undefined,
      };

      const res = await fetch(`/api/assets/${assetId}/save`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Save failed: ${res.status}`);
      }
      setEditingAssetId(null);
      await fetchAssets();
    } catch (err) {
      setError(err.message);
    }
  }

  // ── Delete Asset ────────────────────────────────────────────────────────
  function handleDelete(assetId) {
    const asset = assets.find((candidate) => candidate.id === assetId);
    if (!asset) return;
    setDeleteTarget(asset);
    setDeleteReason('');
    setDeleteError(null);
  }

  function closeDeleteDialog() {
    if (deletingAsset) return;
    setDeleteTarget(null);
    setDeleteReason('');
    setDeleteError(null);
  }

  async function confirmDeleteAsset() {
    if (!deleteTarget) return;
    const isMajor = deleteTarget.status === 'LIVE' || sessionStatus === 'ACTIVE';
    const reason = deleteReason.trim();
    if (isMajor && !reason) {
      setDeleteError('Enter a reason before permanently deleting this asset.');
      return;
    }

    setDeletingAsset(true);
    setDeleteError(null);
    setError(null);
    try {
      const url = reason
        ? `/api/assets/${deleteTarget.id}?reason=${encodeURIComponent(reason)}`
        : `/api/assets/${deleteTarget.id}`;
      const res = await fetch(url, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Delete failed: ${res.status}`);
      }
      setDeleteTarget(null);
      setDeleteReason('');
      await fetchAssets();
    } catch (err) {
      setDeleteError(err.message);
    } finally {
      setDeletingAsset(false);
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
        credentials: 'same-origin',
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

  async function handleDeleteAudio(assetId) {
    setError(null);
    try {
      const res = await fetch(`/api/assets/${assetId}/audio`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
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
    const color = getCategoryColor(category);
    return {
      display: 'inline-block',
      border: `1px solid ${color}`,
      color: color,
      padding: '2px 8px',
      borderRadius: '4px',
      fontSize: '0.75rem',
      fontWeight: 600,
      background: 'transparent',
    };
  }

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('q', searchQuery.trim());
      if (filterCategory !== 'All') {
        params.set('category', filterCategory);
      }
      const res = await fetch(`/api/sessions/${sessionId}/assets?${params.toString()}`, {
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error(`Search failed: ${res.status}`);
      const data = await res.json();
      setSearchResults(data);
      setSortOption('relevance');
    } catch (err) {
      setError(err.message);
      setSearchResults(null);
    } finally {
      setSearching(false);
    }
  }, [searchQuery, filterCategory, sessionId]);

  const handleClearSearch = useCallback(() => {
    setSearchQuery('');
    setSearchResults(null);
  }, []);

  const displayAssets = searchResults !== null ? searchResults : assets;

  const processedAssets = React.useMemo(() => {
    let list = [...displayAssets];

    if (filterStatus !== 'All') {
      list = list.filter((a) => a.status === filterStatus);
    }

    if (filterCategory !== 'All' && searchResults === null) {
      list = list.filter((a) => a.category === filterCategory);
    }

    list.sort((a, b) => {
      const aValMin = a.valuation_min ?? 0;
      const bValMin = b.valuation_min ?? 0;
      const aValMax = a.valuation_max ?? 0;
      const bValMax = b.valuation_max ?? 0;
      const aValAvg = (aValMin + aValMax) / 2;
      const bValAvg = (bValMin + bValMax) / 2;

      switch (sortOption) {
        case 'title_asc':
          return (a.title || '').localeCompare(b.title || '');
        case 'title_desc':
          return (b.title || '').localeCompare(a.title || '');
        case 'category_asc':
          return (a.category || '').localeCompare(b.category || '');
        case 'category_desc':
          return (b.category || '').localeCompare(a.category || '');
        case 'value_high':
          return bValAvg - aValAvg;
        case 'value_low':
          return aValAvg - bValAvg;
        case 'relevance':
          return (b._similarity ?? 0) - (a._similarity ?? 0);
        case 'id_desc':
        default:
          return (b.id || '').localeCompare(a.id || '');
      }
    });

    return list;
  }, [displayAssets, filterStatus, filterCategory, sortOption, searchResults]);

  // ── Recent Activity Reel (last 10 completed items) ──────────────────────
  const recentCompletedAssets = React.useMemo(() => {
    return (assets || [])
      .filter((a) => a.ocr_status === 'COMPLETED')
      .sort((a, b) => (b.id || '').localeCompare(a.id || ''))
      .slice(0, 10);
  }, [assets]);

  // Check for review_required flag
  function hasReviewFlag(asset) {
    let djson = {};
    try {
      if (asset.description_json) {
        djson = typeof asset.description_json === 'string'
          ? JSON.parse(asset.description_json)
          : asset.description_json;
      }
    } catch { /* ignore */ }
    return djson.review_required === true;
  }

  // ── Render ──────────────────────────────────────────────────────────────
  if (!isSetupOrActive) {
    return (
      <div className="archival-card" style={{ textAlign: 'center', padding: 'var(--space-xl)' }}>
        <h3 style={{ marginBottom: 'var(--space-md)' }}>Inventory Dashboard Locked</h3>
        <p className="text-muted">
          The inventory dashboard is only available during the Setup and Active phases. Assets cannot be modified once the session is completed or archived.
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
        <div
          className="banner banner-error"
          style={{
            marginBottom: 'var(--space-md)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 'var(--space-sm)',
            flexWrap: 'wrap',
          }}
        >
          <span>{error}</span>
          {error.includes('inventory refresh') && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setError(null);
                fetchAssets();
              }}
              data-testid="retry-inventory-refresh"
            >
              Retry Inventory
            </button>
          )}
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

      {/* Pending Updates Batch Publish Banner */}
      {pendingUpdatesCount > 0 && (
        <div
          className="archival-card"
          data-testid="pending-updates-banner"
          style={{
            border: '1px solid var(--color-primary)',
            background: 'var(--color-primary-light)',
            padding: 'var(--space-md)',
            borderRadius: 'var(--radius-sm)',
            marginBottom: 'var(--space-md)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 'var(--space-md)',
            flexWrap: 'wrap',
          }}
        >
          <div>
            <h4 style={{ margin: 0, fontFamily: 'var(--font-serif)', color: 'var(--color-primary)' }}>
              📢 Unpublished Inventory Changes
            </h4>
            <p className="text-sm text-muted" style={{ margin: '4px 0 0 0' }}>
              You have <strong>{pendingUpdatesCount}</strong> pending update{pendingUpdatesCount > 1 ? 's' : ''} to the inventory.
              Beneficiaries will not see or be notified of these changes until you publish them.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePublishUpdates}
            disabled={publishingUpdates}
            data-testid="publish-updates-btn"
          >
            {publishingUpdates ? 'Publishing...' : '📣 Publish Updates to Heirs'}
          </button>
        </div>
      )}

      <div className="inventory-workbench">
        <aside className="inventory-capture-pane" aria-label="Quick inventory capture">
          <div className="collapsible-section">
            <button
              type="button"
              className="collapsible-trigger"
              onClick={() => setIsQuickCaptureOpen(!isQuickCaptureOpen)}
              aria-expanded={isQuickCaptureOpen}
              data-testid="quick-capture-toggle"
            >
              <span>📸 Quick Capture{stagingPhotos.length > 0 ? ` (${stagingPhotos.length}/${MAX_STAGING_PHOTOS})` : ''}</span>
              <span>▼</span>
            </button>
          </div>

      {isQuickCaptureOpen && (
      <>
      {/* ── Mobile Camera Hub: Room Selector ─────────────────────────── */}
      <div
        className="archival-card inventory-room-card"
        data-testid="staging-room-selector"
        style={{
          marginBottom: 'var(--space-lg)',
          padding: 'var(--space-md)',
          background: 'var(--color-primary-light)',
          border: '1px solid var(--color-primary)',
        }}
      >
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-md)',
          flexWrap: 'wrap',
        }}>
          <label
            htmlFor="staging-room-select"
            style={{ fontWeight: 600, fontSize: '0.9rem', whiteSpace: 'nowrap' }}
          >
            📍 Staging in:
          </label>
          {showCustomRoomInput ? (
            <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center', flex: 1 }}>
              <input
                type="text"
                className="form-input"
                placeholder="Enter custom location..."
                value={customRoom}
                onChange={(e) => setCustomRoom(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCustomRoomSubmit()}
                style={{ flex: 1, maxWidth: '300px' }}
                data-testid="custom-room-input"
              />
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleCustomRoomSubmit}
                disabled={!customRoom.trim()}
                data-testid="custom-room-submit"
              >
                Set
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setShowCustomRoomInput(false)}
              >
                Cancel
              </button>
            </div>
          ) : (
            <select
              id="staging-room-select"
              className="form-input"
              value={stagingRoom}
              onChange={(e) => handleRoomChange(e.target.value)}
              style={{ flex: 1, maxWidth: '320px' }}
              data-testid="staging-room-dropdown"
            >
              {DEFAULT_ROOMS.map((room) => (
                <option key={room} value={room}>{room}</option>
              ))}
              <option value="__custom__">+ Add Custom Location</option>
            </select>
          )}
        </div>
      </div>

      {/* ── Mobile Camera Hub: Flexible Photo Stack ───────────────────── */}
      <div
        className="archival-card inventory-quick-capture-card"
        data-testid="staging-slots"
        style={{
          marginBottom: 'var(--space-lg)',
          padding: 'var(--space-md)',
        }}
      >
        <h3 style={{ marginBottom: 'var(--space-sm)', fontFamily: 'var(--font-serif)' }}>
          📸 Quick Capture
        </h3>
        <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-md)' }}>
          Capture as many useful photos as this item needs. Stage it once the photo set is ready.
        </p>

        <label
          className="form-label"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 'var(--space-xs)',
            marginBottom: 'var(--space-sm)',
            cursor: 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={autoDescribeImages}
            onChange={(e) => setAutoDescribeImages(e.target.checked)}
            data-testid="auto-describe-toggle"
          />
          AI describe after upload
        </label>

        <div className="photo-label-help">
          <button
            type="button"
            className="photo-label-help__trigger"
            onClick={() => setShowPhotoLabelHelp((current) => !current)}
            aria-expanded={showPhotoLabelHelp}
            aria-controls="photo-label-help-panel"
          >
            <span className="photo-label-help__icon" aria-hidden="true">i</span>
            What do the photo labels mean?
          </button>
          {showPhotoLabelHelp && (
            <div
              id="photo-label-help-panel"
              className="photo-label-help__panel"
              role="region"
              aria-label="Photo label explanation"
            >
              <p>
                Labels simply identify what each photo shows. They help people—and the optional
                AI description—understand why the photo was included.
              </p>
              <dl>
                <div>
                  <dt>Front / Back</dt>
                  <dd>The main sides of the item.</dd>
                </div>
                <div>
                  <dt>Maker / brand mark</dt>
                  <dd>A signature, label, stamp, serial number, or manufacturer logo.</dd>
                </div>
                <div>
                  <dt>Damage / wear</dt>
                  <dd>Scratches, cracks, stains, missing pieces, or other condition issues.</dd>
                </div>
                <div>
                  <dt>Size reference</dt>
                  <dd>The item beside a ruler or familiar object to show its approximate size.</dd>
                </div>
                <div>
                  <dt>Close-up detail</dt>
                  <dd>Craftsmanship, texture, hardware, decoration, or another important feature.</dd>
                </div>
                <div>
                  <dt>Primary photo</dt>
                  <dd>The main image people see first. Use the clearest overall view.</dd>
                </div>
              </dl>
            </div>
          )}
        </div>

        <div className="quick-capture-grid">
          {stagingPhotos.map((photo, idx) => (
            <div
              key={photo.id}
              data-testid={`staging-photo-${idx}`}
              style={{
                border: idx === 0 ? '1px solid var(--color-primary)' : '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                overflow: 'hidden',
                background: 'var(--color-card-bg)',
              }}
            >
              <div style={{ aspectRatio: '4/3', position: 'relative', overflow: 'hidden', background: 'var(--color-bg)' }}>
                <img
                  src={photo.previewUrl}
                  alt={photo.label || `Captured view ${idx + 1}`}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
                {idx === 0 && (
                  <span
                    style={{
                      position: 'absolute',
                      top: 8,
                      left: 8,
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: 'rgba(30, 41, 59, 0.75)',
                      color: '#FFFFFF',
                      fontSize: '0.7rem',
                      fontWeight: 700,
                    }}
                  >
                    Primary
                  </span>
                )}
              </div>
              <div style={{ padding: 'var(--space-xs)', display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)' }}>
                <label
                  htmlFor={`staging-photo-label-${photo.id}`}
                  className="text-xs"
                  style={{ fontWeight: 700, color: 'var(--color-text-muted)' }}
                >
                  What does this photo show?
                </label>
                <input
                  id={`staging-photo-label-${photo.id}`}
                  className="form-input"
                  value={photo.label}
                  onChange={(e) => updateStagingPhotoLabel(photo.id, e.target.value)}
                  placeholder="Type a label or choose one below"
                  data-testid={`staging-photo-label-${idx}`}
                  style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                />
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {PHOTO_LABEL_SUGGESTIONS.map((label) => (
                    <button
                      key={label}
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => updateStagingPhotoLabel(photo.id, label)}
                      style={{ padding: '1px 6px', fontSize: '0.65rem' }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 'var(--space-xs)', alignItems: 'center' }}>
                  {idx !== 0 && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setPrimaryStagingPhoto(photo.id)}
                      style={{ padding: '2px 6px', fontSize: '0.7rem' }}
                      data-testid={`set-primary-photo-${idx}`}
                    >
                      Set Primary
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => setEditingStagingPhotoId(photo.id)}
                    style={{ padding: '2px 6px', fontSize: '0.7rem' }}
                    data-testid={`edit-staging-photo-${idx}`}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => removeStagingPhoto(photo.id)}
                    style={{ padding: '2px 6px', fontSize: '0.7rem', color: 'var(--color-alert)', marginLeft: 'auto' }}
                    data-testid={`remove-staging-photo-${idx}`}
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ))}

          {stagingPhotos.length < MAX_STAGING_PHOTOS && (
            <button
              type="button"
              data-testid="add-staging-photo"
              onClick={triggerCameraCapture}
              style={{
                border: '2px dashed var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                aspectRatio: '4/3',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 4,
                cursor: 'pointer',
                background: 'var(--color-bg)',
                color: 'var(--color-text-muted)',
              }}
            >
              <span style={{ fontSize: '2rem' }}>📷</span>
              <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>
                {stagingPhotos.length === 0 ? 'Add first photo' : 'Add another photo'}
              </span>
            </button>
          )}
        </div>

        {stagingPhotos.length < MAX_STAGING_PHOTOS && (
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 'var(--space-sm)',
            marginBottom: 'var(--space-md)',
          }}>
            <button
              type="button"
              className="btn btn-primary"
              onClick={triggerCameraCapture}
              data-testid="take-staging-photo"
            >
              Take photo
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => stagingFileInputRef.current?.click()}
              data-testid="upload-staging-photos"
            >
              Upload images
            </button>
            <span className="text-xs text-muted">
              Camera works on phones and laptops. You can upload several images at once.
            </span>
          </div>
        )}

        <input
          ref={stagingFileInputRef}
          type="file"
          accept="image/*"
          multiple
          style={{ display: 'none' }}
          onChange={handleStagingFileUpload}
          aria-label="Upload item images"
          data-testid="staging-file-input"
        />

        <input
          ref={cameraCaptureInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          style={{ display: 'none' }}
          onChange={handleCameraCaptureChange}
          aria-label="Take a photo"
          data-testid="camera-capture-input"
        />

        {/* Audio Recording for Staging */}
        <div style={{ marginBottom: 'var(--space-md)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', marginBottom: 'var(--space-xs)' }}>
            <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>🎙 Oral Provenance</span>
            {audioBlob && (
              <span style={{ fontSize: '0.75rem', color: 'var(--color-primary)' }}>
                ✅ Recording captured
              </span>
            )}
          </div>
          <AdminVoiceRecorder
            assetId="staging"
            onSaved={(blob) => handleRecordingSaved(blob)}
            onCleared={clearAudio}
          />
        </div>

        {/* Stage Button */}
        <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleStageFromSlots}
            disabled={isStaging || stagingPhotos.length === 0}
            data-testid="stage-from-slots-btn"
          >
            {isStaging ? stagingStatus || 'Staging...' : '📤 Stage Item'}
          </button>
          {stageSuccess && (
            <span style={{ color: 'var(--color-primary)', fontWeight: 600, fontSize: '0.85rem' }}>
              ✅ Staged!
            </span>
          )}
          {uploadQueue.length > 0 && (
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
              📶 {uploadQueue.length} pending upload
            </span>
          )}
        </div>
      </div>
      </>
      )}

      {/* ── Recent Activity Reel ──────────────────────────────────────── */}
      {recentCompletedAssets.length > 0 && (
        <div
          className="archival-card inventory-recent-reel"
          data-testid="recent-activity-reel"
          style={{ marginBottom: 'var(--space-lg)', padding: 'var(--space-md)' }}
        >
          <h3 style={{ marginBottom: 'var(--space-sm)', fontFamily: 'var(--font-serif)', fontSize: '0.9rem' }}>
            🕐 Recently Staged
          </h3>
          <div style={{
            display: 'flex',
            gap: 'var(--space-sm)',
            overflowX: 'auto',
            paddingBottom: 'var(--space-sm)',
            WebkitOverflowScrolling: 'touch',
          }}>
            {recentCompletedAssets.map((asset) => (
              <div
                key={asset.id}
                data-testid={`recent-item-${asset.id}`}
                style={{
                  minWidth: '140px',
                  maxWidth: '160px',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  overflow: 'hidden',
                  flexShrink: 0,
                  background: 'var(--color-card-bg)',
                }}
              >
                <div style={{ aspectRatio: '4/3', overflow: 'hidden', background: 'var(--color-bg)' }}>
                  {asset.image_uri ? (
                    <img
                      src={asset.image_uri}
                      alt={asset.title || 'Staged item'}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                  ) : (
                    <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-muted)' }}>
                      📷
                    </div>
                  )}
                </div>
                <div style={{ padding: '6px 8px' }}>
                  <p style={{
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    margin: 0,
                  }}>
                    {asset.title || 'Staged Item'}
                  </p>
                  {asset.valuation_min != null && asset.valuation_max != null && (
                    <p style={{ fontSize: '0.6rem', color: 'var(--color-text-muted)', margin: 0 }}>
                      ${asset.valuation_min}–${asset.valuation_max}
                    </p>
                  )}
                  {hasReviewFlag(asset) && (
                    <span style={{
                      display: 'inline-block',
                      marginTop: 2,
                      padding: '1px 4px',
                      borderRadius: '3px',
                      background: '#FEF3C7',
                      color: '#92400E',
                      fontSize: '0.55rem',
                      fontWeight: 700,
                    }}>
                      ⚠ Review
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

        </aside>

        <section className="inventory-management-pane" aria-label="Manage captured inventory">
          <div className="inventory-pane-heading inventory-pane-heading--catalog">
            <div>
              <p className="allocation-eyebrow">Manage captured items</p>
              <h3>Inventory Catalog</h3>
            </div>
            <div className="inventory-pane-stats" aria-label="Catalog summary">
              <span>{assets.length} item{assets.length === 1 ? '' : 's'}</span>
              <span>{categories.length} categor{categories.length === 1 ? 'y' : 'ies'}</span>
            </div>
          </div>

      {/* Collapsible Category Manager */}
      <div className="category-manager-accordion">
        <button
          type="button"
          className="category-manager-trigger"
          onClick={() => setIsCategoryManagerOpen(!isCategoryManagerOpen)}
          aria-expanded={isCategoryManagerOpen}
          data-testid="category-manager-toggle"
        >
          <span>📂 Category Manager ({categories.length})</span>
          <span>▼</span>
        </button>
        {isCategoryManagerOpen && (
          <div className="category-manager-content">
            <p className="text-muted text-sm" style={{ marginBottom: 'var(--space-md)' }}>
              Manage your session's keepsake categories. Categories in use by keepsakes cannot be deleted.
            </p>
            
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-sm)', marginBottom: 'var(--space-md)' }}>
              {categories.map((cat) => (
                <div
                  key={cat}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '4px 12px',
                    border: `1px solid ${getCategoryColor(cat)}`,
                    color: getCategoryColor(cat),
                    borderRadius: '16px',
                    fontSize: '0.85rem',
                    background: 'transparent',
                  }}
                >
                  <span>{cat}</span>
                  <button
                    type="button"
                    onClick={() => handleDeleteCategory(cat)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--color-alert)',
                      cursor: 'pointer',
                      fontSize: '1rem',
                      padding: 0,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                    data-testid={`delete-category-${cat}`}
                    title={`Delete ${cat}`}
                  >
                    &times;
                  </button>
                </div>
              ))}
            </div>

            <form onSubmit={handleCreateCategory} style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
              <input
                type="text"
                className="form-input"
                placeholder="New category name (e.g. Books, Documents)"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                style={{ flex: 1, maxWidth: '300px' }}
                data-testid="new-category-input"
              />
              <button
                type="submit"
                className="btn btn-secondary"
                disabled={categoryCreating || !newCategoryName.trim()}
                data-testid="add-category-btn"
              >
                {categoryCreating ? 'Adding...' : 'Add Category'}
              </button>
            </form>
          </div>
        )}
      </div>

      {/* Desktop file-upload fallback – hidden by default, shown only as a secondary link in the Quick Capture card */}
      <input
        id="asset-file-upload"
        type="file"
        accept="image/*"
        multiple
        style={{ display: 'none' }}
        onChange={handleFileUpload}
        data-testid="asset-file-input"
      />

      {/* RAG Search, Filter, and Sort Toolbar */}
      <div className="collapsible-section" style={{ marginBottom: 'var(--space-md)' }}>
        <button
          type="button"
          className="collapsible-trigger"
          onClick={() => setIsFilterBarOpen(!isFilterBarOpen)}
          aria-expanded={isFilterBarOpen}
          data-testid="filter-bar-toggle"
        >
          <span>🔍 Search &amp; Filter</span>
          <span>▼</span>
        </button>
        {isFilterBarOpen && (
        <div className="collapsible-content" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-md)', alignItems: 'flex-end' }}>

          {/* Search bar with Enter support */}
          <div style={{ flex: 2, minWidth: '280px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label className="form-label text-xs">Search Catalog</label>
            <div style={{ display: 'flex', gap: 'var(--space-sm)', width: '100%', alignItems: 'stretch' }}>
              <div style={{ position: 'relative', flex: 1 }}>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Semantic RAG Search (e.g. mahogany table, gilded vase)..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  style={{ paddingRight: searchQuery ? '2.5rem' : undefined, width: '100%' }}
                  data-testid="admin-search-input"
                />
                {searchQuery && (
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
                disabled={searching || !searchQuery.trim()}
                data-testid="admin-search-submit"
              >
                {searching ? 'Searching...' : 'Search'}
              </button>
            </div>
          </div>

          {/* Category Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label className="form-label text-xs">Category</label>
            <select
              className="form-input"
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
              style={{ minWidth: '140px' }}
              data-testid="admin-filter-category"
            >
              <option value="All">All Categories</option>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          {/* Status Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label className="form-label text-xs">Status</label>
            <select
              className="form-input"
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              style={{ minWidth: '140px' }}
              data-testid="admin-filter-status"
            >
              <option value="All">All Statuses</option>
              <option value="STAGED">Staged (Draft)</option>
              <option value="LIVE">Live Keepsakes</option>
              <option value="PRE_ALLOCATED">Pre-Allocated</option>
            </select>
          </div>

          {/* Sorting */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label className="form-label text-xs">Sort By</label>
            <select
              className="form-input"
              value={sortOption}
              onChange={(e) => setSortOption(e.target.value)}
              style={{ minWidth: '160px' }}
              data-testid="admin-sort-select"
            >
              <option value="id_desc">Date Created (Newest)</option>
              {searchResults !== null && <option value="relevance">RAG Relevance Match</option>}
              <option value="title_asc">Title (A-Z)</option>
              <option value="title_desc">Title (Z-A)</option>
              <option value="category_asc">Category (A-Z)</option>
              <option value="category_desc">Category (Z-A)</option>
              <option value="value_high">Valuation (High to Low)</option>
              <option value="value_low">Valuation (Low to High)</option>
            </select>
          </div>

          {/* Grid/List Toggle */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label className="form-label text-xs">Layout</label>
            <div className="view-toggle-container" style={{ margin: 0 }}>
              <button
                type="button"
                className={`view-toggle-btn ${viewMode === 'grid' ? 'active-toggle' : ''}`}
                onClick={() => setViewMode('grid')}
                data-testid="toggle-grid-view"
              >
                Grid View
              </button>
              <button
                type="button"
                className={`view-toggle-btn ${viewMode === 'list' ? 'active-toggle' : ''}`}
                onClick={() => setViewMode('list')}
                data-testid="toggle-list-view"
              >
                List View
              </button>
            </div>
          </div>

        </div>
        )}
      </div>

      {/* Zero match state */}
      {searchResults !== null && processedAssets.length === 0 && (
        <div className="archival-card" style={{ textAlign: 'center', padding: 'var(--space-xl)', marginBottom: 'var(--space-lg)' }}>
          <p className="text-muted">
            We couldn't find any matches for <strong>"{searchQuery}"</strong> under your selected filters. Try broadening your terms or clearing the search.
          </p>
        </div>
      )}

      {/* Asset display */}
      {processedAssets.length === 0 && searchResults === null ? (
        <div className="archival-card" style={{ textAlign: 'center', padding: 'var(--space-xl)' }}>
          <p className="text-muted">No items found matching the current filters.</p>
        </div>
      ) : (
        <>
          {viewMode === 'grid' ? (
            /* GRID VIEW */
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))',
                gap: 'var(--space-md)',
              }}
            >
              {processedAssets.map((asset) => {
                const isPreAllocating = preAllocatingAssetId === asset.id;
                const showReviewPill = hasReviewFlag(asset);
                const displayDescription = getDisplayDescription(asset);
                const structuredDetails = getStructuredAssetDetails(asset);
                const hasStructuredDetails = hasStructuredAssetDetails(structuredDetails);
                const isDescriptionExpanded = expandedDescriptionIds.has(asset.id);
                const canExpandDescription = displayDescription.length > 120 || hasStructuredDetails;
                return (
                  <div
                    key={asset.id}
                    className="archival-card"
                    data-testid={`asset-card-${asset.id}`}
                    style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)' }}
                  >
                    {/* Image Gallery */}
                    {(asset.image_uri || (asset.images && asset.images.length > 0)) && (
                      <div
                        style={{
                          aspectRatio: '4/3',
                          overflow: 'hidden',
                          borderRadius: 'var(--radius-sm)',
                          border: '1px solid var(--color-border)',
                          background: 'var(--color-bg)',
                        }}
                      >
                        <AssetGallery
                          images={asset.images || [{ id: 'primary', image_uri: asset.image_uri, is_primary: true, angle_label: 'Primary' }]}
                          title={asset.title}
                          onEditImage={(image) => setEditingImage({ assetId: asset.id, image, title: asset.title })}
                        />
                      </div>
                    )}

                    {/* Review Flag Pill */}
                    {showReviewPill && (
                      <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        padding: '2px 8px',
                        borderRadius: '12px',
                        background: '#FEF3C7',
                        color: '#92400E',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        alignSelf: 'flex-start',
                      }}>
                        ⚠️ Needs Review
                      </div>
                    )}

                    {/* Badges */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={categoryBadgeStyle(asset.category || 'Other')}>
                        {asset.category || 'Other'}
                      </span>
                      <div style={{ display: 'flex', gap: 'var(--space-xs)', alignItems: 'center' }}>
                        {asset._similarity !== undefined && (
                          <span className="badge badge-primary" style={{ fontSize: '0.65rem' }}>
                            {Math.round(asset._similarity * 100)}% Match
                          </span>
                        )}
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
                    </div>

                    {/* Metadata display */}
                    <div>
                      <h4 style={{ fontFamily: 'var(--font-serif)', marginBottom: '2px' }}>
                        {asset.title || 'Untitled Asset'}
                      </h4>
                      {(displayDescription || hasStructuredDetails) && (
                        <div style={{ marginBottom: 'var(--space-xs)' }}>
                          {displayDescription && (
                            <p className="text-muted text-sm" style={{
                              overflow: isDescriptionExpanded ? 'visible' : 'hidden',
                              textOverflow: isDescriptionExpanded ? 'clip' : 'ellipsis',
                              display: isDescriptionExpanded ? 'block' : '-webkit-box',
                              WebkitLineClamp: isDescriptionExpanded ? 'unset' : 2,
                              WebkitBoxOrient: 'vertical',
                              marginBottom: canExpandDescription ? '2px' : 'var(--space-xs)'
                            }}>
                              {displayDescription}
                            </p>
                          )}
                          {isDescriptionExpanded && hasStructuredDetails && (
                            <StructuredAssetDetails details={structuredDetails} compact />
                          )}
                          {canExpandDescription && (
                            <button
                              type="button"
                              onClick={() => toggleDescriptionExpanded(asset.id)}
                              className="btn-link"
                              style={{
                                border: 'none',
                                background: 'transparent',
                                color: 'var(--color-primary)',
                                padding: 0,
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                              }}
                              aria-expanded={isDescriptionExpanded}
                              data-testid={`toggle-description-${asset.id}`}
                            >
                              {isDescriptionExpanded ? 'Show less' : 'Show more'}
                            </button>
                          )}
                        </div>
                      )}
                      {asset.valuation_min != null && asset.valuation_max != null && (
                        <p className="text-sm" style={{ color: 'var(--color-text)', margin: 0 }}>
                          ${asset.valuation_min.toLocaleString()} – ${asset.valuation_max.toLocaleString()}
                          {asset.valuation_source && (
                            <span className="text-muted"> · {asset.valuation_source}</span>
                          )}
                        </p>
                      )}
                      {structuredDetails.dimensions && (
                        <p className="text-sm text-muted" style={{ margin: '4px 0 0', whiteSpace: 'pre-line' }}>
                          {structuredDetails.dimensions.split('\n')[0]}
                        </p>
                      )}
                      {asset.sentiment_tag && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '6px' }}>
                          {asset.sentiment_tag.split(',')
                            .map((t) => t.trim())
                            .filter(Boolean)
                            .map((tag, idx) => (
                              <span
                                key={idx}
                                style={{
                                  display: 'inline-block',
                                  padding: '1px 6px',
                                  borderRadius: '12px',
                                  background: 'var(--color-primary-light)',
                                  color: 'var(--color-primary)',
                                  fontSize: '0.65rem',
                                  fontWeight: 500,
                                }}
                              >
                                #{tag}
                              </span>
                            ))
                          }
                        </div>
                      )}
                    </div>

                    {/* AI verification badge */}
                    {asset.ai_feedback && (() => {
                      try { return JSON.parse(asset.ai_feedback)?.rating === 'thumbs_up'; } catch { return false; }
                    })() ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', fontSize: '0.65rem', fontWeight: 600, color: '#22c55e', background: '#dcfce7', borderRadius: '4px', padding: '2px 6px', marginTop: '4px' }}>
                        ✓ Human Verified
                      </span>
                    ) : asset.valuation_source === 'AI Appraisal' ? (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', fontSize: '0.65rem', fontWeight: 500, color: '#92400e', background: '#fef3c7', borderRadius: '4px', padding: '2px 6px', marginTop: '4px' }}>
                        ✨ AI Generated
                      </span>
                    ) : null}

                    {/* Pre-allocated indicator */}
                    {asset.status === 'PRE_ALLOCATED' && asset.pre_allocated_to_heir_name && (
                      <p className="text-sm" style={{ color: 'var(--color-primary)', fontWeight: 600, margin: 0 }}>
                        Pre-Allocated: {asset.pre_allocated_to_heir_name}
                      </p>
                    )}

                    {/* Audio indicator */}
                    {asset.audio_uri && (
                      <div style={{ marginTop: 'var(--space-xs)', marginBottom: 'var(--space-sm)' }}>
                        <p className="text-sm" style={{ color: 'var(--color-primary)', fontWeight: 600, marginBottom: 'var(--space-xs)' }}>
                          🎙 Spoken Story Recorded
                        </p>
                        <audio
                          src={asset.audio_uri.startsWith('/') ? asset.audio_uri : `/${asset.audio_uri}`}
                          controls
                          preload="none"
                          style={{ width: '100%', height: '32px', borderRadius: '4px' }}
                        />
                      </div>
                    )}

                    {/* Pre-allocation selection widget */}
                    {isPreAllocating && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)', padding: 'var(--space-sm)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', background: 'var(--color-bg)' }}>
                        <label className="form-label text-xs">Assign to Heir (Specific Devise)</label>
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

                    {/* Action buttons */}
                    <div style={{
                      display: 'flex',
                      gap: 'var(--space-sm)',
                      flexWrap: 'wrap',
                      marginTop: 'auto',
                      paddingTop: 'var(--space-sm)',
                      borderTop: '1px solid var(--color-border)',
                    }}>
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => startEditing(asset)}
                        data-testid={`edit-btn-${asset.id}`}
                      >
                        {asset.status === 'LIVE' ? 'Edit Details' : 'Edit & Publish'}
                      </button>

                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => setPreviewAsset(asset)}
                        data-testid={`preview-heir-btn-${asset.id}`}
                      >
                        Preview as Heir
                      </button>
                      
                      {asset.status !== 'LIVE' && asset.status !== 'PRE_ALLOCATED' && !isPreAllocating && (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => startPreAllocating(asset.id)}
                          data-testid={`pre-allocate-btn-${asset.id}`}
                        >
                          Pre-Allocate
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

                  </div>
                );
              })}
            </div>
          ) : (
            /* COMPACT LIST VIEW */
            <div className="list-layout">
              {processedAssets.map((asset) => {
                const isPreAllocating = preAllocatingAssetId === asset.id;
                const structuredDetails = getStructuredAssetDetails(asset);
                return (
                  <div key={asset.id} className="list-item-card" data-testid={`asset-card-${asset.id}`}>
                    <div className="list-item-thumb">
                      <img
                        src={normalizeMediaSrc(asset.image_uri || 'static/uploads/placeholder.webp')}
                        alt={asset.title || 'Keepsake'}
                      />
                    </div>
                    
                    <div className="list-item-info">
                      <div className="list-item-title">{asset.title || 'Untitled Asset'}</div>
                      <div className="list-item-meta">
                        <span style={categoryBadgeStyle(asset.category || 'Other')}>
                          {asset.category || 'Other'}
                        </span>
                        <span className="badge" style={{ padding: '0px 6px', fontSize: '0.65rem' }}>
                          {asset.status || 'STAGED'}
                        </span>
                        {asset.valuation_min != null && asset.valuation_max != null && (
                          <span>${asset.valuation_min.toLocaleString()} – ${asset.valuation_max.toLocaleString()}</span>
                        )}
                        {structuredDetails.dimensions && (
                          <span>{structuredDetails.dimensions.split('\n')[0]}</span>
                        )}
                        {asset.audio_uri && <span>🎤 Audio Story</span>}
                        {asset._similarity !== undefined && (
                          <span style={{ color: 'var(--color-primary)', fontWeight: 600 }}>
                            {Math.round(asset._similarity * 100)}% Match
                          </span>
                        )}
                      </div>
                    </div>

                    {isPreAllocating && (
                      <div style={{ display: 'flex', gap: 'var(--space-xs)', alignItems: 'center' }}>
                        <select
                          className="form-input"
                          style={{ padding: '4px', fontSize: '0.75rem', maxWidth: '140px' }}
                          value={selectedHeirId}
                          onChange={(e) => setSelectedHeirId(e.target.value)}
                          data-testid={`pre-allocate-select-${asset.id}`}
                        >
                          <option value="">Select heir...</option>
                          {heirs.map((heir) => (
                            <option key={heir.id} value={heir.id}>
                              {heir.username}
                            </option>
                          ))}
                        </select>
                        <button
                          className="btn btn-primary btn-sm"
                          style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                          onClick={handlePreAllocate}
                          disabled={!selectedHeirId}
                          data-testid={`confirm-pre-allocate-${asset.id}`}
                        >
                          Confirm
                        </button>
                        <button
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                          onClick={cancelPreAllocating}
                        >
                          Cancel
                        </button>
                      </div>
                    )}

                    <div className="list-item-actions">
                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                        onClick={() => startEditing(asset)}
                        data-testid={`edit-btn-${asset.id}`}
                      >
                        Edit
                      </button>

                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                        onClick={() => setPreviewAsset(asset)}
                        data-testid={`preview-heir-btn-${asset.id}`}
                      >
                        Preview
                      </button>
                      
                      {asset.status !== 'LIVE' && asset.status !== 'PRE_ALLOCATED' && !isPreAllocating && (
                        <button
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                          onClick={() => startPreAllocating(asset.id)}
                          data-testid={`pre-allocate-btn-${asset.id}`}
                        >
                          Pre-Allocate
                        </button>
                      )}

                      <button
                        className="btn btn-secondary btn-sm"
                        style={{ padding: '4px 8px', fontSize: '0.75rem', color: '#DC2626' }}
                        onClick={() => handleDelete(asset.id)}
                        data-testid={`delete-btn-${asset.id}`}
                      >
                        🗑
                      </button>
                    </div>

                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

        </section>
      </div>

      {previewAsset && (() => {
        const displayDescription = getDisplayDescription(previewAsset);
        const structuredDetails = getStructuredAssetDetails(previewAsset);
        const hasStructuredDetails = hasStructuredAssetDetails(structuredDetails);
        const previewImages = previewAsset.images?.length
          ? previewAsset.images
          : previewAsset.image_uri
            ? [{ id: 'primary', image_uri: previewAsset.image_uri, is_primary: true, angle_label: 'Primary' }]
            : [];

        return (
          <div
            className="drawer-overlay"
            onClick={() => setPreviewAsset(null)}
            data-testid="heir-preview-modal"
            style={{ alignItems: 'center', justifyContent: 'center', padding: '24px' }}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-labelledby="heir-preview-title"
              onClick={(e) => e.stopPropagation()}
              style={{
                width: 'min(760px, calc(100vw - 32px))',
                maxHeight: 'calc(100vh - 48px)',
                overflowY: 'auto',
                background: 'var(--color-card-bg)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-md)',
                boxShadow: '0 20px 50px rgba(15, 23, 42, 0.22)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 'var(--space-sm)',
                  padding: 'var(--space-md)',
                  borderBottom: '1px solid var(--color-border)',
                }}
              >
                <div>
                  <p className="text-xs text-muted" style={{ marginBottom: 2, fontWeight: 700, textTransform: 'uppercase' }}>
                    Heir preview
                  </p>
                  <h3 id="heir-preview-title" style={{ fontFamily: 'var(--font-serif)', margin: 0 }}>
                    {previewAsset.title || 'Untitled Asset'}
                  </h3>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setPreviewAsset(null)}
                  aria-label="Close heir preview"
                >
                  Close
                </button>
              </div>

              {previewImages.length > 0 && (
                <div style={{ aspectRatio: '4/3', background: 'var(--color-bg)', borderBottom: '1px solid var(--color-border)' }}>
                  <AssetGallery images={previewImages} title={previewAsset.title} />
                </div>
              )}

              <div style={{ padding: 'var(--space-lg)', display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                  <span style={categoryBadgeStyle(previewAsset.category || 'Other')}>
                    {previewAsset.category || 'Other'}
                  </span>
                  {previewAsset.status === 'PRE_ALLOCATED' && (
                    <span className="badge" style={{ color: 'var(--color-alert)' }}>Pre-Allocated</span>
                  )}
                </div>

                {displayDescription && (
                  <p className="text-sm" style={{ color: 'var(--color-text-muted)', lineHeight: 1.55, margin: 0 }}>
                    {displayDescription}
                  </p>
                )}

                {hasStructuredDetails && (
                  <StructuredAssetDetails details={structuredDetails} />
                )}

                {previewAsset.valuation_min != null && previewAsset.valuation_max != null && (
                  <p className="text-sm" style={{ color: 'var(--color-text)', margin: 0, fontWeight: 600 }}>
                    ${previewAsset.valuation_min.toLocaleString()} – ${previewAsset.valuation_max.toLocaleString()}
                    {previewAsset.valuation_source && (
                      <span className="text-muted" style={{ fontWeight: 400 }}> · {previewAsset.valuation_source}</span>
                    )}
                  </p>
                )}

                {previewAsset.sentiment_tag && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {previewAsset.sentiment_tag.split(',')
                      .map((t) => t.trim())
                      .filter(Boolean)
                      .map((tag, idx) => (
                        <span
                          key={idx}
                          style={{
                            display: 'inline-block',
                            padding: '1px 6px',
                            borderRadius: '12px',
                            background: 'var(--color-primary-light)',
                            color: 'var(--color-primary)',
                            fontSize: '0.65rem',
                            fontWeight: 500,
                          }}
                        >
                          #{tag}
                        </span>
                      ))}
                  </div>
                )}

                {previewAsset.audio_uri && (
                  <div>
                    <p className="text-sm" style={{ color: 'var(--color-primary)', fontWeight: 600, marginBottom: 'var(--space-xs)' }}>
                      🎙 Spoken Story
                    </p>
                    <audio
                      src={previewAsset.audio_uri.startsWith('/') ? previewAsset.audio_uri : `/${previewAsset.audio_uri}`}
                      controls
                      preload="none"
                      style={{ width: '100%', height: '32px', borderRadius: '4px' }}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Slide-over Edit Drawer Modal */}
      {editingAssetId && (
        <div className="drawer-overlay" onClick={cancelEditing}>
          <div className="drawer-content" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-header">
              <h3>Edit Keepsake Details</h3>
              <button type="button" className="close-btn" onClick={cancelEditing} aria-label="Close drawer">✕</button>
            </div>

            <div className="drawer-toolbar">
              {/* AI status banner + Generate button row */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-xs)', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                {/* Left: status banner */}
                <div style={{ fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  {(() => {
                    const asset = assets.find((a) => a.id === editingAssetId);
                    let isVerified = false;
                    try { isVerified = JSON.parse(asset?.ai_feedback)?.rating === 'thumbs_up'; } catch { /* not JSON */ }
                    const justGenerated = aiGeneratedAssets[editingAssetId];
                    if (isVerified) {
                      return (
                        <span style={{ color: 'var(--color-success, #22c55e)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
                          ✓ Human Verified
                          <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>— AI generated &amp; reviewed</span>
                        </span>
                      );
                    }
                    if (justGenerated) {
                      return (
                        <span style={{ color: 'var(--color-warning, #f59e0b)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
                          ⚠ AI Generated — please review before verifying
                        </span>
                      );
                    }
                    if (asset?.valuation_source === 'AI Appraisal') {
                      return (
                        <span style={{ color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                          ✨ AI Generated — not yet verified
                        </span>
                      );
                    }
                    return null;
                  })()}
                </div>
                {/* Right: buttons */}
                <div style={{ display: 'flex', gap: 'var(--space-xs)', alignItems: 'center' }}>
                  {(() => {
                    const asset = assets.find((a) => a.id === editingAssetId);
                    try { return JSON.parse(asset?.ai_feedback)?.rating === 'thumbs_up'; } catch { return false; }
                  })() ? (
                    <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#22c55e', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      ✓ Verified
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => handleVerifyAsset(editingAssetId)}
                      disabled={verifyingAssets[editingAssetId]}
                      style={{ background: '#22c55e', color: '#fff', border: 'none', fontWeight: 600 }}
                    >
                      {verifyingAssets[editingAssetId] ? 'Saving...' : '✓ Mark as Verified'}
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleGenerateDetails(editingAssetId)}
                    disabled={generatingDetails[editingAssetId]}
                    data-testid={`generate-ai-btn-${editingAssetId}`}
                    style={{ display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    {generatingDetails[editingAssetId] ? 'Analyzing image...' : '✨ Generate with AI'}
                  </button>
                </div>
              </div>

              {error && (
                <div className="banner banner-error" style={{ marginBottom: 'var(--space-xs)', padding: 'var(--space-xs)', fontSize: '0.78rem' }}>
                  {error}
                </div>
              )}

              <div className="edit-detail-tabs" role="tablist" aria-label="Keepsake detail sections">
                {EDIT_DETAIL_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={activeEditTab === tab.id}
                    className={`edit-detail-tab ${activeEditTab === tab.id ? 'active' : ''}`}
                    onClick={() => setActiveEditTab(tab.id)}
                    data-testid={`edit-tab-${tab.id}`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="drawer-body">
              {activeEditTab === 'dimensions' && (
              <div style={{ padding: 'var(--space-sm)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', background: 'var(--color-bg)' }}>
                <h5 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-xs)', fontSize: '0.9rem' }}>
                  Logistics Dimensions
                </h5>
                <div className="admin-form-grid">
                  <div>
                    <label className="form-label">Length (in)</label>
                    <input
                      className="form-input"
                      type="number"
                      min={0}
                      step="0.1"
                      value={editForm.length_in ?? ''}
                      onChange={(e) => handleEditFieldChange('length_in', e.target.value)}
                      placeholder="Optional"
                      data-testid={`edit-length-${editingAssetId}`}
                    />
                  </div>
                  <div>
                    <label className="form-label">Width (in)</label>
                    <input
                      className="form-input"
                      type="number"
                      min={0}
                      step="0.1"
                      value={editForm.width_in ?? ''}
                      onChange={(e) => handleEditFieldChange('width_in', e.target.value)}
                      placeholder="Optional"
                      data-testid={`edit-width-${editingAssetId}`}
                    />
                  </div>
                  <div>
                    <label className="form-label">Height (in)</label>
                    <input
                      className="form-input"
                      type="number"
                      min={0}
                      step="0.1"
                      value={editForm.height_in ?? ''}
                      onChange={(e) => handleEditFieldChange('height_in', e.target.value)}
                      placeholder="Optional"
                      data-testid={`edit-height-${editingAssetId}`}
                    />
                  </div>
                  <div>
                    <label className="form-label">Weight (lb)</label>
                    <input
                      className="form-input"
                      type="number"
                      min={0}
                      step="0.1"
                      value={editForm.weight_lb ?? ''}
                      onChange={(e) => handleEditFieldChange('weight_lb', e.target.value)}
                      placeholder="Optional"
                      data-testid={`edit-weight-${editingAssetId}`}
                    />
                  </div>
                </div>
                <div className="admin-form-grid" style={{ marginTop: 'var(--space-xs)' }}>
                  <div>
                    <label className="form-label">Dimension Source</label>
                    <input
                      className="form-input"
                      value={editForm.dimension_source || ''}
                      onChange={(e) => handleEditFieldChange('dimension_source', e.target.value)}
                      placeholder="Measured, AI Estimate, label..."
                      data-testid={`edit-dimension-source-${editingAssetId}`}
                    />
                  </div>
                  <div>
                    <label className="form-label">Confidence</label>
                    <select
                      className="form-input"
                      value={editForm.dimension_confidence || ''}
                      onChange={(e) => handleEditFieldChange('dimension_confidence', e.target.value)}
                      data-testid={`edit-dimension-confidence-${editingAssetId}`}
                    >
                      {DIMENSION_CONFIDENCE_OPTIONS.map((option) => (
                        <option key={option || 'blank'} value={option}>
                          {option || 'Not specified'}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div style={{ marginTop: 'var(--space-xs)' }}>
                  <label className="form-label">Logistics Notes</label>
                  <textarea
                    className="form-input"
                    value={editForm.dimension_notes || ''}
                    onChange={(e) => handleEditFieldChange('dimension_notes', e.target.value)}
                    rows={2}
                    placeholder="Estimated from image, needs measuring, fragile, awkward to carry..."
                    data-testid={`edit-dimension-notes-${editingAssetId}`}
                  />
                </div>
              </div>
              )}

              {activeEditTab === 'basics' && (
              <>
              <div>
                <label className="form-label">Title</label>
                <input
                  className="form-input"
                  value={editForm.title}
                  onChange={(e) => handleEditFieldChange('title', e.target.value)}
                  placeholder="Item title"
                  data-testid={`edit-title-${editingAssetId}`}
                />
              </div>

              <div>
                <label className="form-label">Description (Short Summary)</label>
                <textarea
                  className="form-input"
                  value={editForm.description}
                  onChange={(e) => handleEditFieldChange('description', e.target.value)}
                  rows={2}
                  placeholder="Brief description for the asset card..."
                  data-testid={`edit-description-${editingAssetId}`}
                />
              </div>
              <div>
                <label className="form-label">Category</label>
                <select
                  className="form-input"
                  value={editForm.category}
                  onChange={(e) => handleEditFieldChange('category', e.target.value)}
                  data-testid={`edit-category-${editingAssetId}`}
                >
                  {categories.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </div>
              </>
              )}

              {activeEditTab === 'specifications' && (
              <div>
                <label className="form-label">Specifications</label>
                <textarea
                  className="form-input"
                  value={editForm.specifications || ''}
                  onChange={(e) => handleEditFieldChange('specifications', e.target.value)}
                  rows={3}
                  placeholder="Bullet points: materials, dimensions, hardware..."
                  data-testid={`edit-specifications-${editingAssetId}`}
                />
              </div>
              )}

              {activeEditTab === 'condition' && (
              <div>
                <label className="form-label">Condition Report</label>
                <textarea
                  className="form-input"
                  value={editForm.condition_report || ''}
                  onChange={(e) => handleEditFieldChange('condition_report', e.target.value)}
                  rows={2}
                  placeholder="Visible wear, scratches, damage..."
                  data-testid={`edit-condition-report-${editingAssetId}`}
                />
              </div>
              )}

              {activeEditTab === 'search' && (
              <div>
                <label className="form-label">Search Keywords</label>
                <input
                  className="form-input"
                  value={editForm.keywords || ''}
                  onChange={(e) => handleEditFieldChange('keywords', e.target.value)}
                  placeholder="Comma-separated tags for search optimization..."
                  data-testid={`edit-keywords-${editingAssetId}`}
                />
              </div>
              )}

              {activeEditTab === 'estimate' && (
              <>
              <div className="admin-form-grid">
                <div>
                  <label className="form-label">Min Value ($)</label>
                  <input
                    className="form-input"
                    type="number"
                    min={0}
                    value={editForm.valuation_min}
                    onChange={(e) => handleEditFieldChange('valuation_min', Number(e.target.value))}
                    data-testid={`edit-min-${editingAssetId}`}
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
                    data-testid={`edit-max-${editingAssetId}`}
                  />
                </div>
              </div>

              <div>
                <label className="form-label">Valuation Source</label>
                <select
                  className="form-input"
                  value={editForm.valuation_source}
                  onChange={(e) => handleEditFieldChange('valuation_source', e.target.value)}
                  data-testid={`edit-source-${editingAssetId}`}
                >
                  {VALUATION_SOURCES.map((src) => (
                    <option key={src} value={src}>{src}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="form-label">Sentiment Tags</label>
                <input
                  className="form-input"
                  value={editForm.sentiment_tag}
                  onChange={(e) => handleEditFieldChange('sentiment_tag', e.target.value)}
                  placeholder="e.g. Heirloom, Handmade (comma-separated)..."
                  data-testid={`edit-sentiment-${editingAssetId}`}
                  style={{ marginBottom: '8px' }}
                />

                {editForm.sentiment_tag.trim() && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '8px' }}>
                    {editForm.sentiment_tag.split(',')
                      .map((t) => t.trim())
                      .filter(Boolean)
                      .map((tag, idx) => (
                        <span
                          key={idx}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px',
                            padding: '2px 8px',
                            borderRadius: '12px',
                            background: 'var(--color-primary-light)',
                            color: 'var(--color-primary)',
                            fontSize: '0.75rem',
                            fontWeight: 500,
                          }}
                        >
                          {tag}
                          <button
                            type="button"
                            onClick={() => {
                              const updated = editForm.sentiment_tag.split(',')
                                .map((t) => t.trim())
                                .filter((t) => t !== tag)
                                .join(', ');
                              handleEditFieldChange('sentiment_tag', updated);
                            }}
                            style={{
                              border: 'none',
                              background: 'none',
                              color: 'var(--color-primary)',
                              cursor: 'pointer',
                              fontSize: '0.85rem',
                              padding: 0,
                              lineHeight: 1,
                            }}
                            title="Remove tag"
                          >
                            &times;
                          </button>
                        </span>
                      ))
                    }
                  </div>
                )}

                <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: 'var(--space-sm)' }}>
                  <span style={{ marginRight: '6px' }}>Suggestions:</span>
                  {['Memento', 'Heirloom', 'Practical', 'Antique', 'Handmade', 'Documents'].map((sug) => {
                    const tagsArray = editForm.sentiment_tag.split(',').map(t => t.trim()).filter(Boolean);
                    const isSelected = tagsArray.includes(sug);
                    return (
                      <button
                        key={sug}
                        type="button"
                        onClick={() => {
                          let updated;
                          if (isSelected) {
                            updated = tagsArray.filter(t => t !== sug).join(', ');
                          } else {
                            updated = [...tagsArray, sug].join(', ');
                          }
                          handleEditFieldChange('sentiment_tag', updated);
                        }}
                        style={{
                          border: '1px solid var(--color-border)',
                          borderRadius: '12px',
                          padding: '2px 8px',
                          marginRight: '4px',
                          marginBottom: '4px',
                          cursor: 'pointer',
                          backgroundColor: isSelected ? 'var(--color-primary)' : 'transparent',
                          color: isSelected ? '#FFFFFF' : 'var(--color-text)',
                          fontSize: '0.7rem',
                          transition: 'all 0.2s',
                        }}
                        data-testid={`suggested-tag-${sug}`}
                      >
                        {isSelected ? `✓ ${sug}` : `+ ${sug}`}
                      </button>
                    );
                  })}
                </div>
              </div>
              </>
              )}

              {/* Keepsake Photo Angles & Views */}
              {activeEditTab === 'images' && (
              <>
              <div style={{ marginTop: 'var(--space-sm)', padding: 'var(--space-sm)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', background: 'var(--color-primary-light)' }}>
                <h5 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-xs)', fontSize: '0.85rem' }}>
                  Keepsake Photo Angles & Views
                </h5>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)', marginBottom: 'var(--space-sm)' }}>
                  {(() => {
                    const currentAsset = assets.find(a => a.id === editingAssetId);
                    const assetImages = currentAsset?.images?.length
                      ? currentAsset.images
                      : currentAsset?.image_uri
                        ? [{ id: 'primary', image_uri: currentAsset.image_uri, is_primary: true, angle_label: 'Primary' }]
                        : [];
                    return assetImages.map((img) => (
                      <div key={img.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 'var(--space-xs)', background: 'var(--color-card-bg)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
                          <img
                            src={normalizeMediaSrc(img.image_uri)}
                            alt={img.angle_label}
                            style={{ width: 32, height: 32, objectFit: 'cover', borderRadius: 'var(--radius-sm)' }}
                          />
                          <span className="text-xs font-semibold">{img.angle_label || 'View'}</span>
                          {img.is_primary && <span className="badge badge-primary" style={{ fontSize: '0.55rem', padding: '0px 3px' }}>Primary</span>}
                        </div>
                        <div style={{ display: 'flex', gap: 'var(--space-xs)', alignItems: 'center' }}>
                          <button
                            type="button"
                            onClick={() => setEditingImage({ assetId: editingAssetId, image: img, title: currentAsset?.title })}
                            className="btn btn-secondary btn-sm"
                            style={{ padding: '2px 6px', fontSize: '0.7rem' }}
                            data-testid={`edit-image-btn-${img.id}`}
                          >
                            Edit
                          </button>
                          {!img.is_primary && (
                            <button
                              type="button"
                              onClick={() => handleSecondaryDelete(editingAssetId, img.id)}
                              className="btn btn-danger btn-sm"
                              style={{ padding: '2px 6px', fontSize: '0.7rem' }}
                              data-testid={`delete-image-btn-${img.id}`}
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </div>
                    ));
                  })()}
                </div>

                {secondaryError && (
                  <div className="banner banner-error" style={{ marginBottom: 'var(--space-xs)', padding: 'var(--space-xs)', fontSize: '0.75rem' }}>
                    {secondaryError}
                  </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)' }}>
                  <div className="admin-form-grid">
                    <div>
                      <label className="form-label text-xs" style={{ marginBottom: '2px' }}>Choose Photo File</label>
                      <input
                        type="file"
                        accept="image/*"
                        onChange={(e) => setSecondaryFile(e.target.files?.[0] || null)}
                        style={{ fontSize: '0.75rem', width: '100%' }}
                        data-testid={`secondary-image-file-${editingAssetId}`}
                      />
                    </div>
                    <div>
                      <label className="form-label text-xs" style={{ marginBottom: '2px' }}>Angle / View Label</label>
                      <input
                        className="form-input"
                        type="text"
                        placeholder="Back view, markings..."
                        value={secondaryAngleLabel}
                        onChange={(e) => setSecondaryAngleLabel(e.target.value)}
                        style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                        data-testid={`secondary-image-label-${editingAssetId}`}
                      />
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    style={{ alignSelf: 'flex-end', padding: '4px 8px', fontSize: '0.75rem' }}
                    disabled={secondaryUploading || !secondaryFile}
                    onClick={() => handleSecondaryUpload(editingAssetId)}
                    data-testid={`upload-secondary-btn-${editingAssetId}`}
                  >
                    {secondaryUploading ? 'Uploading view...' : 'Upload View'}
                  </button>
                </div>
              </div>

              {/* Voice Story section in Drawer */}
              <div style={{ marginTop: 'var(--space-sm)', padding: 'var(--space-sm)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', background: 'var(--color-primary-light)' }}>
                <h5 style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-xs)', fontSize: '0.85rem' }}>
                  Voice Story Recording
                </h5>
                {(() => {
                  const currentAsset = assets.find(a => a.id === editingAssetId);
                  return (
                    <>
                      {currentAsset?.audio_uri && (
                        <div style={{ marginBottom: 'var(--space-sm)' }}>
                          <p className="text-xs text-muted" style={{ fontWeight: 600, marginBottom: '4px' }}>
                            🎙 Current voice story:
                          </p>
                          <audio
                            src={currentAsset.audio_uri.startsWith('/') ? currentAsset.audio_uri : `/${currentAsset.audio_uri}`}
                            controls
                            preload="none"
                            style={{ width: '100%', height: '32px', borderRadius: '4px' }}
                          />
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleDeleteAudio(editingAssetId)}
                            style={{ color: 'var(--color-alert)', marginTop: '4px', fontSize: '0.7rem', padding: '2px 6px' }}
                            data-testid={`delete-audio-btn-${editingAssetId}`}
                          >
                            Remove Audio
                          </button>
                        </div>
                      )}
                      
                      <AdminVoiceRecorder
                        assetId={editingAssetId}
                        onSaved={async () => {
                          await fetchAssets();
                        }}
                      />
                    </>
                  );
                })()}
              </div>
              </>
              )}

            </div>

            <div className="drawer-footer">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handlePublish(editingAssetId)}
                data-testid={`publish-btn-${editingAssetId}`}
              >
                Publish Live
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => handleSave(editingAssetId)}
                data-testid={`save-btn-${editingAssetId}`}
              >
                Save Draft
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={cancelEditing}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteTarget && (
        <div
          className="drawer-overlay"
          role="presentation"
          onClick={closeDeleteDialog}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1200,
            display: 'grid',
            placeItems: 'center',
            padding: 'var(--space-md)',
            background: 'rgba(15, 23, 42, 0.55)',
          }}
        >
          <div
            className="archival-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-asset-title"
            onClick={(event) => event.stopPropagation()}
            style={{
              width: 'min(520px, calc(100vw - 32px))',
              padding: 'var(--space-lg)',
              boxShadow: '0 24px 70px rgba(15, 23, 42, 0.3)',
            }}
            data-testid="delete-asset-dialog"
          >
            <h3
              id="delete-asset-title"
              style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-sm)' }}
            >
              Permanently delete this asset?
            </h3>
            <p style={{ marginBottom: 'var(--space-sm)' }}>
              <strong>{deleteTarget.title || 'Untitled Asset'}</strong> and its uploaded photos
              {deleteTarget.audio_uri ? ', audio recording,' : ''} will be permanently removed.
            </p>
            <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-md)' }}>
              This action cannot be undone.
            </p>

            {(deleteTarget.status === 'LIVE' || sessionStatus === 'ACTIVE') && (
              <div style={{ marginBottom: 'var(--space-md)' }}>
                <label className="form-label" htmlFor="delete-asset-reason">
                  Reason for deletion
                </label>
                <textarea
                  id="delete-asset-reason"
                  className="form-input"
                  rows={3}
                  value={deleteReason}
                  onChange={(event) => setDeleteReason(event.target.value)}
                  placeholder="Explain why this published or active-session asset must be removed."
                  data-testid="delete-asset-reason"
                />
              </div>
            )}

            {deleteError && (
              <div className="banner banner-error" style={{ marginBottom: 'var(--space-md)' }}>
                {deleteError}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-sm)' }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={closeDeleteDialog}
                disabled={deletingAsset}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={confirmDeleteAsset}
                disabled={deletingAsset}
                data-testid="confirm-delete-asset"
              >
                {deletingAsset ? 'Deleting...' : 'Permanently Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {aiGenerationError && (
        <div
          className="drawer-overlay"
          role="presentation"
          onClick={() => setAiGenerationError(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1300,
            display: 'grid',
            placeItems: 'center',
            padding: 'var(--space-md)',
            background: 'rgba(15, 23, 42, 0.55)',
          }}
        >
          <div
            className="archival-card"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="ai-generation-error-title"
            onClick={(event) => event.stopPropagation()}
            style={{
              width: 'min(480px, calc(100vw - 32px))',
              padding: 'var(--space-lg)',
              boxShadow: '0 24px 70px rgba(15, 23, 42, 0.3)',
            }}
            data-testid="ai-generation-error-dialog"
          >
            <h3
              id="ai-generation-error-title"
              style={{ fontFamily: 'var(--font-serif)', marginBottom: 'var(--space-sm)', color: 'var(--color-alert, #dc2626)' }}
            >
              ⚠ AI Generation Failed
            </h3>
            <p style={{ marginBottom: 'var(--space-md)' }}>{aiGenerationError}</p>
            <p className="text-sm text-muted" style={{ marginBottom: 'var(--space-md)' }}>
              No fields were changed. You can try again or fill in details manually.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setAiGenerationError(null)}
                data-testid="dismiss-ai-generation-error"
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}

      {editingStagingPhotoId && (() => {
        const photo = stagingPhotos.find((item) => item.id === editingStagingPhotoId);
        if (!photo) return null;
        return (
          <ImageEditModal
            image={{ image_uri: photo.previewUrl, angle_label: photo.label || 'Captured photo' }}
            title={photo.label || 'Captured photo'}
            onCancel={() => setEditingStagingPhotoId(null)}
            onSave={handleSaveEditedStagingPhoto}
          />
        );
      })()}

      {editingImage && (
        <ImageEditModal
          image={editingImage.image}
          title={editingImage.title}
          saving={imageEditSaving}
          onCancel={() => setEditingImage(null)}
          onSave={handleSaveEditedImage}
        />
      )}

    </div>
  );
}
