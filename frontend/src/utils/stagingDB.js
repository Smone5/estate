/**
 * stagingDB — IndexedDB-backed offline staging cache.
 *
 * Stores captured photos and item staging states locally in IndexedDB.
 * Progress is never lost if the phone restarts or goes offline.
 *
 * Used by AdminInventoryDashboard for the mobile camera hub workflow.
 */

const DB_NAME = 'EstateStewardStaging';
const DB_VERSION = 1;
const STORE_NAME = 'stagingQueue';

/**
 * Open (or create) the staging IndexedDB database.
 * @returns {Promise<IDBDatabase>}
 */
function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'asset_id' });
        store.createIndex('by_created_at', 'created_at', { unique: false });
        store.createIndex('by_upload_status', 'upload_status', { unique: false });
      }
    };

    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

/**
 * Save a staging item to IndexedDB.
 * @param {object} item - { asset_id, session_id, location, primary_blob, secondary_blobs, audio_blob, created_at, upload_status }
 * @returns {Promise<void>}
 */
export async function saveStagingItem(item) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);

    const record = {
      ...item,
      created_at: item.created_at || new Date().toISOString(),
      upload_status: item.upload_status || 'pending',
    };

    const request = store.put(record);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);

    tx.oncomplete = () => db.close();
  });
}

/**
 * Load all staging items from IndexedDB, sorted by creation date (oldest first).
 * @returns {Promise<Array<object>>}
 */
export async function loadStagingItems() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('by_created_at');
    const request = index.getAll();

    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);

    tx.oncomplete = () => db.close();
  });
}

/**
 * Load pending staging items (those not yet uploaded).
 * @returns {Promise<Array<object>>}
 */
export async function loadPendingStagingItems() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('by_upload_status');
    const request = index.getAll('pending');

    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);

    tx.oncomplete = () => db.close();
  });
}

/**
 * Delete a staging item by asset_id.
 * @param {string} assetId
 * @returns {Promise<void>}
 */
export async function deleteStagingItem(assetId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const request = store.delete(assetId);

    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);

    tx.oncomplete = () => db.close();
  });
}

/**
 * Update the upload_status of a staging item.
 * @param {string} assetId
 * @param {'pending'|'uploading'|'uploaded'|'failed'} status
 * @returns {Promise<void>}
 */
export async function updateStagingItemStatus(assetId, status) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const getReq = store.get(assetId);

    getReq.onsuccess = () => {
      const record = getReq.result;
      if (record) {
        record.upload_status = status;
        store.put(record);
      }
    };
    getReq.onerror = () => reject(getReq.error);

    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
    tx.onabort = () => {
      db.close();
      reject(tx.error || new Error('IndexedDB transaction was aborted'));
    };
  });
}

/**
 * Clear all staging items from IndexedDB.
 * @returns {Promise<void>}
 */
export async function clearStagingItems() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const request = store.clear();

    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);

    tx.oncomplete = () => db.close();
  });
}

/**
 * Get the count of pending staging items.
 * @returns {Promise<number>}
 */
export async function getPendingCount() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const index = store.index('by_upload_status');
    const request = index.count('pending');

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);

    tx.oncomplete = () => db.close();
  });
}
