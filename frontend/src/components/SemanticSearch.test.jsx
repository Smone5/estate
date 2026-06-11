// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import SemanticSearch from './SemanticSearch';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

// Mock the Zustand store
vi.mock('../store/useMediationStore', () => {
  const storeState = {
    assets: [
      { id: '1', title: 'Asset One', category: 'Jewelry', image_uri: 'img1.webp', status: 'LIVE' },
      { id: '2', title: 'Asset Two', category: 'Furniture', image_uri: 'img2.webp', status: 'LIVE' },
      { id: '3', title: 'Asset Three', category: 'Art', image_uri: 'img3.webp', status: 'PRE_ALLOCATED' },
    ],
    valuations: {
      '1': { points: 100, reasoning: 'Reason 1', is_reasoning_shared: true },
      '2': { points: 0, reasoning: '', is_reasoning_shared: false },
    },
    session_id: 'session-123',
    addMessage: vi.fn(),
  };

  const useStoreMock = (selector) => selector(storeState);
  useStoreMock.getState = () => storeState;
  return {
    useMediationStore: useStoreMock,
  };
});

describe('SemanticSearch Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  it('renders search input and asset list initially', () => {
    render(<SemanticSearch />);
    expect(screen.getByPlaceholderText(/Search assets/i)).toBeInTheDocument();
    expect(screen.getByText('Asset One')).toBeInTheDocument();
    expect(screen.getByText('Asset Two')).toBeInTheDocument();
  });

  it('filters assets by category client-side when filter is selected', async () => {
    render(<SemanticSearch />);
    
    // Toggle filters panel
    fireEvent.click(screen.getByRole('button', { name: /Filters/i }));
    
    // Click Jewelry category button
    const jewelryBtn = screen.getByRole('button', { name: 'Jewelry' });
    fireEvent.click(jewelryBtn);

    // Jewelry asset should be present, Furniture asset should be filtered out
    expect(screen.getByText('Asset One')).toBeInTheDocument();
    expect(screen.queryByText('Asset Two')).not.toBeInTheDocument();
  });

  it('filters assets by allocation status client-side', () => {
    render(<SemanticSearch />);
    
    fireEvent.click(screen.getByRole('button', { name: /Filters/i }));
    
    // Click Allocated filter
    fireEvent.click(screen.getByRole('button', { name: /^Allocated/ }));
    
    expect(screen.getByText('Asset One')).toBeInTheDocument();
    expect(screen.queryByText('Asset Two')).not.toBeInTheDocument();
  });

  it('performs vector similarity search on backend and displays match percentage', async () => {
    const mockSearchResults = [
      { id: '1', title: 'Matched Asset', category: 'Jewelry', image_uri: 'img1.webp', status: 'LIVE', _similarity: 0.85 }
    ];
    
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockSearchResults,
    });

    render(<SemanticSearch />);
    
    const input = screen.getByPlaceholderText(/Search assets/i);
    fireEvent.change(input, { target: { value: 'matched' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/sessions/session-123/assets?q=matched');
    });

    expect(await screen.findByText('Matched Asset')).toBeInTheDocument();
    expect(screen.getByText('85% Match')).toBeInTheDocument();
  });

  it('displays zero-match fallback state and handle Ask the Mediator button', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<SemanticSearch />);
    
    const input = screen.getByPlaceholderText(/Search assets/i);
    fireEvent.change(input, { target: { value: 'nothing' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled();
    });

    // Zero match card should appear
    expect(await screen.findByText(/We couldn't find a close match for/i)).toBeInTheDocument();
    
    // Click Ask the Mediator
    const askBtn = screen.getByRole('button', { name: /Ask the Mediator/i });
    fireEvent.click(askBtn);

    const store = useMediationStore.getState();
    expect(store.addMessage).toHaveBeenCalledWith({
      sender: 'heir',
      text: 'Did you find any "nothing" in the estate?',
    });
  });
});
