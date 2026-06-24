// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import AdminHelpPortal from './AdminHelpPortal';
import '@testing-library/jest-dom';

describe('AdminHelpPortal Component', () => {
  const sessionId = 'session-123';
  const mockFaqs = [
    { id: 'f1', question: 'When is the deadline?', answer: 'Before next Friday.' },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
    // Mock window.confirm
    global.window.confirm = vi.fn(() => true);
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = render(<AdminHelpPortal isOpen={false} onClose={() => {}} sessionId={sessionId} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders tutorials and fetches published custom FAQs when open', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockFaqs,
    });

    render(<AdminHelpPortal isOpen={true} onClose={() => {}} sessionId={sessionId} />);

    // Verify tutorial sections
    expect(screen.getByTestId('tutorial-section-1')).toBeInTheDocument();
    expect(screen.getByTestId('tutorial-section-2')).toBeInTheDocument();
    expect(screen.getByTestId('tutorial-section-3')).toBeInTheDocument();
    expect(screen.getByTestId('tutorial-section-4')).toBeInTheDocument();
    expect(screen.getByTestId('tutorial-section-5')).toBeInTheDocument();

    // Verify loading Custom FAQs
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${sessionId}/faqs`);
      expect(screen.getByText('When is the deadline?')).toBeInTheDocument();
      expect(screen.getByText('Before next Friday.')).toBeInTheDocument();
    });
  });

  it('allows creating a custom FAQ', async () => {
    // 1. Initial list load
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });
    // 2. Submit POST response
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 'f2', question: 'New Question', answer: 'New Answer' }),
    });
    // 3. Reload list response
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: 'f2', question: 'New Question', answer: 'New Answer' }],
    });

    render(<AdminHelpPortal isOpen={true} onClose={() => {}} sessionId={sessionId} />);

    await screen.findByText(/No custom guidelines published yet/i);

    // Fill the form
    fireEvent.change(screen.getByLabelText(/^Question/i), { target: { value: 'New Question' } });
    fireEvent.change(screen.getByLabelText(/^Answer/i), { target: { value: 'New Answer' } });

    // Submit form
    fireEvent.submit(screen.getByRole('button', { name: /Publish Guideline/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${sessionId}/faqs`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: 'New Question', answer: 'New Answer' }),
      });
    });

    // Verify new item renders
    expect(await screen.findByText('New Question')).toBeInTheDocument();
  });

  it('allows editing an existing custom FAQ', async () => {
    // 1. Initial list load
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockFaqs,
    });
    // 2. Submit PUT response
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 'f1', question: 'Updated Question', answer: 'Before next Friday.' }),
    });
    // 3. Reload list response
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: 'f1', question: 'Updated Question', answer: 'Before next Friday.' }],
    });

    render(<AdminHelpPortal isOpen={true} onClose={() => {}} sessionId={sessionId} />);

    // Wait for item to render
    const item = await screen.findByTestId('faq-item-f1');
    expect(item).toBeInTheDocument();

    // Click Edit button
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));

    // Change input
    const input = screen.getByLabelText(/^Question/i);
    expect(input.value).toBe('When is the deadline?');
    fireEvent.change(input, { target: { value: 'Updated Question' } });

    // Submit
    fireEvent.submit(screen.getByRole('button', { name: /Update Guideline/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${sessionId}/faqs/f1`, {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: 'Updated Question', answer: 'Before next Friday.' }),
      });
    });

    expect(await screen.findByText('Updated Question')).toBeInTheDocument();
  });

  it('allows deleting a custom FAQ', async () => {
    // 1. Initial list load
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockFaqs,
    });
    // 2. Delete request response
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'success' }),
    });
    // 3. Reload list response
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<AdminHelpPortal isOpen={true} onClose={() => {}} sessionId={sessionId} />);

    // Wait for item to render
    const item = await screen.findByTestId('faq-item-f1');
    expect(item).toBeInTheDocument();

    // Click Delete button
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => {
      expect(global.window.confirm).toHaveBeenCalled();
      expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${sessionId}/faqs/f1`, {
        method: 'DELETE',
        credentials: 'same-origin',
      });
    });

    // Item should be gone
    expect(await screen.findByText(/No custom guidelines published yet/i)).toBeInTheDocument();
  });
});
