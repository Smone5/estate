/**
 * imageCompression — Client-side canvas-based image compression.
 *
 * Downscales high-resolution mobile photos (10MB+) to max 2048px on the
 * longest edge with quality 0.85, reducing payload size by ~97% (~300KB).
 *
 * Used by AdminInventoryDashboard before uploading to the backend.
 */

/**
 * Compress an image File or Blob to a smaller Blob.
 *
 * @param {File|Blob} file - The source image file
 * @param {number} maxDimension - Max width/height in pixels (default 2048)
 * @param {number} quality - Output quality 0.0-1.0 (default 0.85)
 * @param {string} outputFormat - 'image/webp' or 'image/jpeg' (default 'image/webp')
 * @returns {Promise<Blob>} Compressed image Blob
 */
export async function compressImage(
  file,
  maxDimension = 2048,
  quality = 0.85,
  outputFormat = 'image/webp'
) {
  // If the browser doesn't support WebP encoding, fall back to JPEG
  const canvas = document.createElement('canvas');
  const testData = canvas.toDataURL('image/webp');
  if (!testData.startsWith('data:image/webp') && outputFormat === 'image/webp') {
    outputFormat = 'image/jpeg';
  }

  // Load the image from the file
  const imageBitmap = await createImageBitmap(file);
  const { width, height } = imageBitmap;

  // Calculate new dimensions while preserving aspect ratio
  let newWidth = width;
  let newHeight = height;

  if (width > height && width > maxDimension) {
    newWidth = maxDimension;
    newHeight = Math.round((height / width) * maxDimension);
  } else if (height > maxDimension) {
    newHeight = maxDimension;
    newWidth = Math.round((width / height) * maxDimension);
  }

  // Draw the resized image onto a canvas and export
  canvas.width = newWidth;
  canvas.height = newHeight;

  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(imageBitmap, 0, 0, newWidth, newHeight);

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          // Preserve original filename extension when possible
          const filename = file.name || 'image.webp';
          const nameParts = filename.split('.');
          const ext = outputFormat === 'image/webp' ? 'webp' : 'jpg';
          const newFilename = nameParts.length > 1
            ? [...nameParts.slice(0, -1), ext].join('.')
            : `${nameParts[0]}.${ext}`;

          const renamedBlob = new Blob([blob], {
            type: outputFormat,
          });
          renamedBlob.name = newFilename;
          resolve(renamedBlob);
        } else {
          // Fallback — return original file as JPEG
          reject(new Error('Canvas toBlob returned null'));
        }
      },
      outputFormat,
      quality
    );
  });
}

/**
 * Check if the image likely needs compression (larger than ~500KB).
 *
 * @param {File|Blob} file
 * @returns {boolean}
 */
export function shouldCompress(file) {
  // Always compress images larger than 500KB
  return file.size > 500 * 1024;
}

/**
 * Compress an image only if it's large enough to warrant it.
 * Returns the original file for small images.
 *
 * @param {File|Blob} file
 * @param {number} maxDimension
 * @param {number} quality
 * @returns {Promise<{blob: Blob, wasCompressed: boolean}>}
 */
export async function autoCompress(file, maxDimension = 2048, quality = 0.85) {
  if (shouldCompress(file)) {
    const compressed = await compressImage(file, maxDimension, quality);
    return { blob: compressed, wasCompressed: true };
  }
  return { blob: file, wasCompressed: false };
}