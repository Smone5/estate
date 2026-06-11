// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import ModelTransparencyModal from './ModelTransparencyModal';
import '@testing-library/jest-dom';

const mockModels = [
  {
    component: 'Fast Mediator (System 1)',
    name: 'Qwen-2.5-8B-Instruct',
    parameters: '8.0B',
    license: 'Apache-2.0',
    provenance: 'Pretrained on Qwen open training datasets; fine-tuned for instruction-following.',
  },
  {
    component: 'Slow Critic (System 2)',
    name: 'Qwen-2.5-14B-Instruct',
    parameters: '14.2B',
    license: 'Apache-2.0',
    provenance: 'Pretrained and post-trained by Alibaba Cloud; optimized for reasoning and logical validation.',
  },
  {
    component: 'Vision OCR Engine',
    name: 'Llava-1.5',
    parameters: '7.0B',
    license: 'Apache-2.0',
    provenance: 'CLIP ViT-L/14 visual encoder and Llama-2; trained on public multi-modal datasets.',
  },
  {
    component: 'Local Speech Synthesis (TTS)',
    name: 'Kokoro-82M ONNX',
    parameters: '82M',
    license: 'Apache-2.0 / Custom Research',
    provenance: 'Trained on public domain and CC-licensed audio datasets. Runs locally on CPU.',
  },
  {
    component: 'Semantic Search & RAG Embedding Engine',
    name: 'nomic-embed-text',
    parameters: '137M',
    license: 'Apache-2.0',
    provenance: 'Trained by Nomic AI on public web text. Generates 768-dimensional dense vectors for estate asset similarity search and RAG context retrieval.',
  },
];

describe('ModelTransparencyModal Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <ModelTransparencyModal isOpen={false} onClose={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('fetches models from /api/system/models when opened', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ models: mockModels }),
    });

    render(<ModelTransparencyModal isOpen={true} onClose={() => {}} />);

    // Should show loading initially
    expect(screen.getByText(/Loading model information/i)).toBeInTheDocument();

    // Wait for fetch to complete and models to render
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/system/models');
    });

    // Verify all 5 model rows render
    await waitFor(() => {
      const rows = screen.getAllByTestId(/^model-row-/);
      expect(rows).toHaveLength(5);
    });

    // Verify specific model content
    expect(screen.getByText('Qwen-2.5-8B-Instruct (8.0B)')).toBeInTheDocument();
    expect(screen.getByText('Qwen-2.5-14B-Instruct (14.2B)')).toBeInTheDocument();
    expect(screen.getByText('Llava-1.5 (7.0B)')).toBeInTheDocument();
    expect(screen.getByText('Kokoro-82M ONNX (82M)')).toBeInTheDocument();
    expect(screen.getByText('nomic-embed-text (137M)')).toBeInTheDocument();
  });

  it('shows AB 2013 compliance header', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ models: mockModels }),
    });

    render(<ModelTransparencyModal isOpen={true} onClose={() => {}} />);

    const header = await screen.findByText('AI Model Details & Training Transparency');
    expect(header).toBeInTheDocument();

    const ab2013 = await screen.findByText(/California Assembly Bill 2013/);
    expect(ab2013).toBeInTheDocument();
  });

  it('shows error message on fetch failure', async () => {
    global.fetch.mockRejectedValueOnce(new Error('Network error'));

    render(<ModelTransparencyModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('shows error banner on non-ok response', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
    });

    render(<ModelTransparencyModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load model transparency data')).toBeInTheDocument();
    });
  });

  it('shows empty state when no models returned', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ models: [] }),
    });

    render(<ModelTransparencyModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(
        screen.getByText('No model transparency data available at this time.')
      ).toBeInTheDocument();
    });
  });

  it('closes modal when backdrop is clicked', async () => {
    const onClose = vi.fn();
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ models: mockModels }),
    });

    render(<ModelTransparencyModal isOpen={true} onClose={onClose} />);

    const backdrop = await screen.findByTestId('transparency-backdrop');
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes modal when close button is clicked', async () => {
    const onClose = vi.fn();
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ models: mockModels }),
    });

    render(<ModelTransparencyModal isOpen={true} onClose={onClose} />);

    const closeBtn = await screen.findByLabelText('Close');
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('displays license information for each model', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ models: mockModels }),
    });

    render(<ModelTransparencyModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getAllByText(/License: Apache-2.0/).length).toBeGreaterThanOrEqual(4);
    });
  });

  it('does not re-fetch when closed and re-opened via prop change', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ models: mockModels }),
    });
    global.fetch = fetchSpy;

    const { rerender } = render(
      <ModelTransparencyModal isOpen={true} onClose={() => {}} />
    );

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });

    // Close
    rerender(<ModelTransparencyModal isOpen={false} onClose={() => {}} />);

    // Re-open
    rerender(<ModelTransparencyModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });
  });
});