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
        LLM_PROVIDER: { value: 'openai', secret: false, choices: ['ollama', 'openai', 'anthropic'] },
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

  it('only shows credential fields for providers actually selected, and shares one key across slots', async () => {
    const settingsWithMultiProvider = {
      llm: {
        LLM_PROVIDER: { value: 'nvidia', secret: false, choices: ['ollama', 'openai', 'anthropic', 'nvidia'] },
        VISION_PROVIDER: { value: 'nvidia', secret: false, choices: ['ollama', 'openai', 'anthropic', 'nvidia'] },
        EMBEDDING_PROVIDER: { value: 'ollama', secret: false, choices: ['ollama', 'openai', 'anthropic', 'nvidia'] },
        OLLAMA_BASE_URL: { value: 'http://host.docker.internal:11434', secret: false, choices: null },
        NVIDIA_API_KEY: { is_set: true, secret: true, choices: null },
        NVIDIA_BASE_URL: { value: 'https://integrate.api.nvidia.com/v1', secret: false, choices: null },
        OPENAI_API_KEY: { is_set: false, secret: true, choices: null },
        ANTHROPIC_API_KEY: { is_set: false, secret: true, choices: null },
        GEMINI_API_KEY: { is_set: false, secret: true, choices: null },
        OPENROUTER_API_KEY: { is_set: false, secret: true, choices: null },
        OPENROUTER_BASE_URL: { value: '', secret: false, choices: null },
      },
    };
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => settingsWithMultiProvider });

    render(<AdminSettingsPanel />);

    // NVIDIA is used for both LLM and Vision — its key/base-url fields
    // should appear exactly once each, not duplicated.
    expect(await screen.findAllByLabelText('Nvidia Api Key')).toHaveLength(1);
    expect(screen.getAllByLabelText('Nvidia Base Url')).toHaveLength(1);

    // Ollama is used for embeddings — its base URL should show too.
    expect(screen.getByLabelText('Ollama Base Url')).toBeInTheDocument();

    // OpenAI/Anthropic/Gemini/OpenRouter aren't selected anywhere — hidden.
    expect(screen.queryByLabelText('Openai Api Key')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Anthropic Api Key')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Gemini Api Key')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Openrouter Api Key')).not.toBeInTheDocument();
  });

  it('auto-fills the vision model when the vision provider changes', async () => {
    const settingsWithVision = {
      llm: {
        VISION_PROVIDER: { value: 'ollama', secret: false, choices: ['ollama', 'openai', 'anthropic'] },
        VISION_MODEL: { value: 'llava:latest', secret: false, choices: null },
      },
    };
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => settingsWithVision })
      .mockResolvedValueOnce({ ok: true, json: async () => settingsWithVision });

    render(<AdminSettingsPanel />);

    await screen.findByDisplayValue('llava:latest');

    fireEvent.change(screen.getByLabelText('Vision Provider'), { target: { value: 'anthropic' } });
    expect(screen.getByLabelText('Vision Model')).toHaveValue('claude-sonnet-4-6');

    fireEvent.click(screen.getByRole('button', { name: /Save LLM Provider/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/admin/settings',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({
            updates: { VISION_PROVIDER: 'anthropic', VISION_MODEL: 'claude-sonnet-4-6' },
          }),
        }),
      );
    });
  });

  const settingsWithFastModel = {
    llm: {
      ...baseSettings.llm,
      FAST_THINKER_MODEL: { value: 'qwen3:8b', secret: false, choices: null },
    },
  };

  it('tests an LLM connection using current draft values and shows the result', async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => settingsWithFastModel })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true, detail: 'OK', elapsed_ms: 123 }),
      });

    render(<AdminSettingsPanel />);

    await screen.findByDisplayValue('ollama');
    fireEvent.click(screen.getByTestId('test-connection-fast'));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/admin/settings/test-connection',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"purpose":"fast"'),
        }),
      );
    });

    expect(await screen.findByTestId('test-connection-result-fast')).toHaveTextContent('✓ OK (123ms)');
  });

  it('shows the error message when a connection test fails', async () => {
    global.fetch
      .mockResolvedValueOnce({ ok: true, json: async () => settingsWithFastModel })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: false, error: 'connection refused' }),
      });

    render(<AdminSettingsPanel />);

    await screen.findByDisplayValue('ollama');
    fireEvent.click(screen.getByTestId('test-connection-fast'));

    expect(await screen.findByTestId('test-connection-result-fast')).toHaveTextContent('✗ connection refused');
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
