// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import BIP39RestorePanel from './BIP39RestorePanel';
import '@testing-library/jest-dom';

describe('BIP39RestorePanel Component', () => {
  beforeEach(() => {
    global.fetch = vi.fn();

    // Mock URL methods
    global.URL.createObjectURL = vi.fn(() => 'blob:test');
    global.URL.revokeObjectURL = vi.fn();

    // Mock document.createElement for download
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = originalCreateElement(tag);
      if (tag === 'a') {
        el.click = vi.fn();
      }
      return el;
    });

    // Mock window.location.reload
    Object.defineProperty(window, 'location', {
      value: { reload: vi.fn() },
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Rendering ───────────────────────────────────────────────────────────
  it('renders the backup and restore UI', () => {
    render(<BIP39RestorePanel />);

    expect(screen.getByTestId('bip39-restore-panel')).toBeInTheDocument();
    expect(screen.getByText('System Backup & Disaster Recovery')).toBeInTheDocument();
    expect(screen.getByText('Generate System Backup')).toBeInTheDocument();
    expect(screen.getByTestId('download-backup-btn')).toBeInTheDocument();
    expect(screen.getByTestId('upload-restore-btn')).toBeInTheDocument();
    expect(screen.getByTestId('recovery-key-textarea')).toBeInTheDocument();
  });

  // ── Download Backup ─────────────────────────────────────────────────────
  it('downloads backup successfully', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => new Blob(['test'], { type: 'application/octet-stream' }),
    });

    render(<BIP39RestorePanel />);

    fireEvent.click(screen.getByTestId('download-backup-btn'));

    await waitFor(() => {
      expect(screen.getByText('System backup downloaded successfully.')).toBeInTheDocument();
    });
  });

  it('shows error on failed backup download', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Backup generation failed' }),
      status: 500,
    });

    render(<BIP39RestorePanel />);

    fireEvent.click(screen.getByTestId('download-backup-btn'));

    await waitFor(() => {
      expect(screen.getByText('Backup generation failed')).toBeInTheDocument();
    });
  });

  it('shows loading state on download button', () => {
    global.fetch.mockImplementationOnce(() => new Promise(() => {}));

    render(<BIP39RestorePanel />);

    fireEvent.click(screen.getByTestId('download-backup-btn'));

    expect(screen.getByText('Generating Backup...')).toBeInTheDocument();
  });

  // ── Recovery Key Word Count ─────────────────────────────────────────────
  it('tracks word count in the recovery key textarea', () => {
    render(<BIP39RestorePanel />);

    const textarea = screen.getByTestId('recovery-key-textarea');
    fireEvent.change(textarea, {
      target: { value: 'abandon ability able about above absent' },
    });

    const indicator = screen.getByTestId('word-count-indicator');
    expect(indicator.textContent).toContain('6 of 24 words entered');
  });

  it('shows default label when no words entered', () => {
    render(<BIP39RestorePanel />);

    const indicator = screen.getByTestId('word-count-indicator');
    expect(indicator.textContent).toContain('Leave blank if restoring to the same system');
  });

  // ── Restore Validation ──────────────────────────────────────────────────
  it('shows error if recovery key has wrong word count', async () => {
    render(<BIP39RestorePanel />);

    const textarea = screen.getByTestId('recovery-key-textarea');
    fireEvent.change(textarea, {
      target: { value: 'one two three' },
    });

    // File input change directly triggers performRestore which validates word count
    const fileInput = screen.getByTestId('restore-file-input');
    const file = new File(['test'], 'backup.estate.bak', { type: 'application/octet-stream' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('Paper Recovery Key must be exactly 24 words if provided.')).toBeInTheDocument();
    });
  });

  // ── Restore Success ────────────────────────────────────────────────────
  it('uploads and restores backup successfully without recovery key', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'restored' }),
    });

    render(<BIP39RestorePanel />);

    const fileInput = screen.getByTestId('restore-file-input');
    const file = new File(['test'], 'backup.estate.bak', { type: 'application/octet-stream' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByTestId('restore-progress-overlay')).toBeInTheDocument();
      expect(screen.getByText(/Restoring system state/)).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(
        screen.getByText(/System restore successful/),
      ).toBeInTheDocument();
    });
  });

  it('uploads and restores with valid recovery key', async () => {
    const twentyFourWords = [
      'abandon', 'ability', 'able', 'about', 'above', 'absent',
      'absorb', 'abstract', 'absurd', 'abuse', 'access', 'accident',
      'account', 'accuse', 'achieve', 'acid', 'acoustic', 'acquire',
      'across', 'act', 'action', 'actor', 'actress', 'actual',
    ].join(' ');

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'restored' }),
    });

    render(<BIP39RestorePanel />);

    // Type 24 words
    fireEvent.change(screen.getByTestId('recovery-key-textarea'), {
      target: { value: twentyFourWords },
    });

    expect(screen.getByTestId('word-count-indicator').textContent).toContain(
      '24 of 24 words entered',
    );

    // Select restore file
    const fileInput = screen.getByTestId('restore-file-input');
    const file = new File(['test'], 'backup.estate.bak', { type: 'application/octet-stream' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText(/System restore successful/)).toBeInTheDocument();
    });
  });

  // ── Restore Error ──────────────────────────────────────────────────────
  it('shows error on failed restore', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Decryption failed: invalid key' }),
      status: 400,
    });

    render(<BIP39RestorePanel />);

    const fileInput = screen.getByTestId('restore-file-input');
    const file = new File(['test'], 'backup.estate.bak', { type: 'application/octet-stream' });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText('Decryption failed: invalid key')).toBeInTheDocument();
    });

    // Progress overlay should be removed
    await waitFor(() => {
      expect(screen.queryByTestId('restore-progress-overlay')).not.toBeInTheDocument();
    });
  });
});