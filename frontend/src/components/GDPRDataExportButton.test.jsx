// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import GDPRDataExportButton from './GDPRDataExportButton';
import '@testing-library/jest-dom';

describe('GDPRDataExportButton Component', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    global.URL.createObjectURL = vi.fn(() => 'blob:test');
    global.URL.revokeObjectURL = vi.fn();

    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      const el = originalCreateElement(tag);
      if (tag === 'a') {
        el.click = vi.fn();
      }
      return el;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the export button', () => {
    render(<GDPRDataExportButton />);
    expect(screen.getByTestId('export-my-data-btn')).toBeInTheDocument();
    expect(screen.getByText('Export My Data (JSON)')).toBeInTheDocument();
  });

  it('triggers download on successful export', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => new Blob(['{"data": "test"}'], { type: 'application/json' }),
    });

    render(<GDPRDataExportButton />);

    fireEvent.click(screen.getByTestId('export-my-data-btn'));

    await waitFor(() => {
      expect(screen.getByText('Export My Data (JSON)')).toBeInTheDocument();
    });
  });

  it('displays error on export failure', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Export not available' }),
      status: 500,
    });

    render(<GDPRDataExportButton />);

    fireEvent.click(screen.getByTestId('export-my-data-btn'));

    await waitFor(() => {
      expect(screen.getByText('Export not available')).toBeInTheDocument();
    });
  });

  it('shows loading state while exporting', () => {
    global.fetch.mockImplementationOnce(() => new Promise(() => {}));

    render(<GDPRDataExportButton />);

    fireEvent.click(screen.getByTestId('export-my-data-btn'));

    expect(screen.getByText('Exporting...')).toBeInTheDocument();
  });
});