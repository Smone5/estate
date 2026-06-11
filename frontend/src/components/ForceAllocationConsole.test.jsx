// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import ForceAllocationConsole from './ForceAllocationConsole';
import '@testing-library/jest-dom';

describe('ForceAllocationConsole Component', () => {
  const sessionId = 'session-123';
  const mockHeirs = [
    { id: 'h1', username: 'heir_one', legal_first_name: 'Jane', legal_last_name: 'Doe' },
    { id: 'h2', username: 'heir_two', legal_first_name: 'John', legal_last_name: 'Smith' },
  ];
  const mockAssets = [
    { id: 'a1', title: 'Grandfather Clock', category: 'Furniture', description: 'Ancient clock', status: 'LIVE' },
  ];
  const mockValuationsH1 = [
    { asset_id: 'a1', points: 600, reasoning: 'I love it', is_reasoning_shared: true },
  ];
  const mockValuationsH2 = [
    { asset_id: 'a1', points: 400, reasoning: 'Needs repair', is_reasoning_shared: true },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  it('renders loading state initially', () => {
    // Return unresolved promise to test loading state
    global.fetch.mockReturnValue(new Promise(() => {}));
    render(<ForceAllocationConsole sessionId={sessionId} />);
    expect(screen.getByText(/Loading Force Allocation Console/i)).toBeInTheDocument();
  });

  it('fetches heirs, assets, and valuations, and renders contested assets with overlapping bids', async () => {
    // Setup fetch mocks
    global.fetch.mockImplementation((url) => {
      if (url.includes('/heirs/h1/valuations')) {
        return Promise.resolve({ ok: true, json: async () => mockValuationsH1 });
      }
      if (url.includes('/heirs/h2/valuations')) {
        return Promise.resolve({ ok: true, json: async () => mockValuationsH2 });
      }
      if (url.includes('/heirs')) {
        return Promise.resolve({ ok: true, json: async () => mockHeirs });
      }
      if (url.includes('/assets')) {
        return Promise.resolve({ ok: true, json: async () => mockAssets });
      }
      return Promise.reject(new Error('Unknown url'));
    });

    render(<ForceAllocationConsole sessionId={sessionId} />);

    // Wait for loading to finish and contested assets to appear
    expect(await screen.findByText('Grandfather Clock')).toBeInTheDocument();
    expect(screen.getByText('heir_one')).toBeInTheDocument();
    expect(screen.getByText('heir_two')).toBeInTheDocument();
    expect(screen.getByText('600 pts')).toBeInTheDocument();
    expect(screen.getByText('400 pts')).toBeInTheDocument();
  });

  it('enforces fiduciary reason validation and beneficiary selection', async () => {
    global.fetch.mockImplementation((url) => {
      if (url.includes('/heirs/h1/valuations')) return Promise.resolve({ ok: true, json: async () => mockValuationsH1 });
      if (url.includes('/heirs/h2/valuations')) return Promise.resolve({ ok: true, json: async () => mockValuationsH2 });
      if (url.includes('/heirs')) return Promise.resolve({ ok: true, json: async () => mockHeirs });
      if (url.includes('/assets')) return Promise.resolve({ ok: true, json: async () => mockAssets });
      return Promise.reject(new Error('Unknown url'));
    });

    render(<ForceAllocationConsole sessionId={sessionId} />);

    // Wait for card to render
    expect(await screen.findByText('Grandfather Clock')).toBeInTheDocument();

    // The submit button shouldn't exist or be enabled initially
    const submitBtn = screen.queryByRole('button', { name: /Submit Override Allocations/i });
    expect(submitBtn).toBeDisabled();

    // Select beneficiary h1
    const select = screen.getByLabelText(/Assign Beneficiary/i);
    fireEvent.change(select, { target: { value: 'h1' } });

    // The textarea for reason should now be visible
    const reasonTextarea = screen.getByLabelText(/Fiduciary Override Reason/i);
    expect(reasonTextarea).toBeInTheDocument();

    // Enter a very short reason (invalid, length < 5)
    fireEvent.change(reasonTextarea, { target: { value: 'abc' } });
    expect(screen.getByText('Reason must be at least 5 characters.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Submit Override Allocations/i })).toBeDisabled();

    // Enter a valid reason
    fireEvent.change(reasonTextarea, { target: { value: 'Decedent will instructions' } });
    expect(screen.queryByText('Reason must be at least 5 characters.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Submit Override Allocations/i })).not.toBeDisabled();
  });

  it('submits overrides payload and calls onOverrideComplete on success', async () => {
    global.fetch.mockImplementation((url, options) => {
      if (options && options.method === 'POST' && url.includes('/override')) {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'resolved' }) });
      }
      if (url.includes('/heirs/h1/valuations')) return Promise.resolve({ ok: true, json: async () => mockValuationsH1 });
      if (url.includes('/heirs/h2/valuations')) return Promise.resolve({ ok: true, json: async () => mockValuationsH2 });
      if (url.includes('/heirs')) return Promise.resolve({ ok: true, json: async () => mockHeirs });
      if (url.includes('/assets')) return Promise.resolve({ ok: true, json: async () => mockAssets });
      return Promise.reject(new Error('Unknown url'));
    });

    const onCompleteMock = vi.fn();
    render(<ForceAllocationConsole sessionId={sessionId} onOverrideComplete={onCompleteMock} />);

    // Wait for loading to finish
    expect(await screen.findByText('Grandfather Clock')).toBeInTheDocument();

    // Select beneficiary
    fireEvent.change(screen.getByLabelText(/Assign Beneficiary/i), { target: { value: 'h1' } });
    // Write valid reason
    fireEvent.change(screen.getByLabelText(/Fiduciary Override Reason/i), {
      target: { value: 'Mutual written agreement of all heirs.' }
    });

    // Click submit
    const submitBtn = screen.getByRole('button', { name: /Submit Override Allocations/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${sessionId}/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([
          {
            asset_id: 'a1',
            allocated_to_id: 'h1',
            reason: 'Mutual written agreement of all heirs.',
          }
        ]),
      });
      expect(screen.getByText(/Fiduciary overrides successfully applied/i)).toBeInTheDocument();
      expect(onCompleteMock).toHaveBeenCalled();
    });
  });
});
