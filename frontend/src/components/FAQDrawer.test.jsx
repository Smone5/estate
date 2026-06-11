// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import FAQDrawer from './FAQDrawer';
import '@testing-library/jest-dom';

// Mock the Zustand store
vi.mock('../store/useMediationStore', () => {
  const storeState = {
    session_id: 'session-123',
  };
  const useStoreMock = (selector) => selector(storeState);
  useStoreMock.getState = () => storeState;
  return {
    useMediationStore: useStoreMock,
  };
});

describe('FAQDrawer Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = render(<FAQDrawer isOpen={false} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders general FAQs and fetches custom guidelines when open', async () => {
    const mockCustomFaqs = [
      { id: '1', question: 'What is the address?', answer: '123 Main St.' },
    ];
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockCustomFaqs,
    });

    render(<FAQDrawer isOpen={true} onClose={() => {}} />);

    // Verify header and static FAQ is there
    expect(screen.getByText('Help & FAQs')).toBeInTheDocument();
    expect(screen.getByText('How does the point allocation system work?')).toBeInTheDocument();

    // Verify it fetches custom FAQs
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/sessions/session-123/faqs');
      expect(screen.getByText('What is the address?')).toBeInTheDocument();
    });
  });

  it('toggles accordion answer visibility on click', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    render(<FAQDrawer isOpen={true} onClose={() => {}} />);

    const trigger = screen.getByText('Are my points visible to my family members?');
    // Initially, answer content shouldn't be expanded
    expect(screen.queryByText(/Individual point allocations are kept/i)).not.toBeInTheDocument();

    // Click to open
    fireEvent.click(trigger);
    expect(screen.getByText(/Individual point allocations are kept/i)).toBeInTheDocument();

    // Click to close
    fireEvent.click(trigger);
    expect(screen.queryByText(/Individual point allocations are kept/i)).not.toBeInTheDocument();
  });

  it('calls onClose when backdrop or close button is clicked', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    });

    const onCloseMock = vi.fn();
    render(<FAQDrawer isOpen={true} onClose={onCloseMock} />);

    // Click close button
    const closeBtn = screen.getByRole('button', { name: /Close Help/i });
    fireEvent.click(closeBtn);
    expect(onCloseMock).toHaveBeenCalledTimes(1);

    // Click backdrop
    const backdrop = screen.getByTestId('drawer-backdrop');
    fireEvent.click(backdrop);
    expect(onCloseMock).toHaveBeenCalledTimes(2);
  });
});
