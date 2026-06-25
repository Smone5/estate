// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import AdminSettingsPanel from './AdminSettingsPanel';

const baseSettings = {
  llm: {
    LLM_PROVIDER: { value: 'ollama', secret: false, choices: ['ollama', 'openai', 'anthropic'] },
    OPENAI_API_KEY: { is_set: false, secret: true, choices: null },
  },
  smtp: {
    SMTP_HOST: { value: 'localhost', secret: false, choices: null },
  },
  storage: {
    STORAGE_DRIVER: { value: 'LOCAL', secret: false, choices: ['LOCAL', 'S3'] },
  },
};

describe('AdminSettingsPanel', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches and renders settings when expanded', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => baseSettings });

    render(<AdminSettingsPanel />);

    expect(await screen.findByDisplayValue('ollama')).toBeInTheDocument();
    
    // Switch to Email (SMTP) tab to see SMTP settings
    fireEvent.click(screen.getByRole('button', { name: /Email \(SMTP\)/i }));
    expect(await screen.findByDisplayValue('localhost')).toBeInTheDocument();
    
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/admin/settings',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
  });

  it('shows "configured" placeholder for a secret that is already set, never the value', async () => {
    const settingsWithSecret = {
      ...baseSettings,
      llm: {
        ...baseSettings.llm,
        OPENAI_API_KEY: { is_set: true, secret: true, choices: null },
      },
    };
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => settingsWithSecret });

    render(<AdminSettingsPanel />);

    const secretInput = await screen.findByLabelText('Openai Api Key');
    expect(secretInput).toHaveAttribute('type', 'password');
    expect(secretInput.value).toBe('');
    expect(secretInput).toHaveAttribute('placeholder', '•••• configured');
  });

  it('only sends touched fields on save', async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => baseSettings })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ...baseSettings,
          llm: { ...baseSettings.llm, LLM_PROVIDER: { value: 'openai', secret: false, choices: baseSettings.llm.LLM_PROVIDER.choices } },
        }),
      });

    render(<AdminSettingsPanel />);

    await screen.findByDisplayValue('ollama');

    fireEvent.change(screen.getByLabelText('Llm Provider'), { target: { value: 'openai' } });
    fireEvent.click(screen.getByRole('button', { name: /Save LLM Provider/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/admin/settings',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ updates: { LLM_PROVIDER: 'openai' } }),
        }),
      );
    });
  });

  it('shows an error banner when the save request fails', async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => baseSettings })
      .mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ detail: 'Unsupported setting key(s)' }) });

    render(<AdminSettingsPanel />);

    await screen.findByDisplayValue('ollama');

    fireEvent.change(screen.getByLabelText('Llm Provider'), { target: { value: 'openai' } });
    fireEvent.click(screen.getByRole('button', { name: /Save LLM Provider/i }));

    expect(await screen.findByText('Unsupported setting key(s)')).toBeInTheDocument();
  });
});
