// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import '@testing-library/jest-dom';
import AbstentionWaitScreen from './AbstentionWaitScreen';
import AbstentionWaiverModal from './AbstentionWaiverModal';
import HeirValuationPanel from './HeirValuationPanel';
import { useMediationStore } from '../store/useMediationStore';

// Mock Zustand store state
const mockStoreState = {
  unallocatedPoints: 1000,
  isSubmitted: false,
  sessionStatus: 'ACTIVE',
  userStatus: 'ACTIVE',
  legal_first_name: 'John',
  legal_middle_name: null,
  legal_last_name: 'Doe',
  submitValuations: vi.fn(),
  abstainSession: vi.fn(),
  downloadWaiverReceipt: vi.fn(),
  inventoryUpdatedNotice: null,
};

vi.mock('../store/useMediationStore', () => {
  const useStoreMock = (selector) => {
    if (typeof selector === 'function') {
      return selector(mockStoreState);
    }
    return mockStoreState;
  };
  useStoreMock.getState = () => mockStoreState;
  useStoreMock.setState = vi.fn((newVal) => {
    Object.assign(mockStoreState, newVal);
  });
  return {
    useMediationStore: useStoreMock,
  };
});

describe('Abstention and Valuation UI Components', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStoreState.unallocatedPoints = 1000;
    mockStoreState.isSubmitted = false;
    mockStoreState.sessionStatus = 'ACTIVE';
    mockStoreState.userStatus = 'ACTIVE';
    mockStoreState.legal_first_name = 'John';
    mockStoreState.legal_middle_name = null;
    mockStoreState.legal_last_name = 'Doe';
    mockStoreState.inventoryUpdatedNotice = null;
  });

  describe('AbstentionWaitScreen', () => {
    it('renders active abstention layout when userStatus is ABSTAINED', () => {
      mockStoreState.userStatus = 'ABSTAINED';
      render(<AbstentionWaitScreen />);

      expect(screen.getByText('Mediation Opt-Out Registered')).toBeInTheDocument();
      expect(screen.getByText(/You have voluntarily chosen to abstain/i)).toBeInTheDocument();
      expect(screen.getByTestId('download-receipt-btn')).toBeInTheDocument();
    });

    it('triggers downloadWaiverReceipt when download button is clicked', async () => {
      mockStoreState.userStatus = 'ABSTAINED';
      mockStoreState.downloadWaiverReceipt.mockResolvedValueOnce();

      render(<AbstentionWaitScreen />);
      const btn = screen.getByTestId('download-receipt-btn');
      fireEvent.click(btn);

      await waitFor(() => {
        expect(mockStoreState.downloadWaiverReceipt).toHaveBeenCalled();
      });
    });

    it('renders expired non-participating layout when userStatus is EXPIRED_NON_PARTICIPATING', () => {
      mockStoreState.userStatus = 'EXPIRED_NON_PARTICIPATING';
      render(<AbstentionWaitScreen />);

      expect(screen.getByText('Invitation Link Expired')).toBeInTheDocument();
      expect(screen.getByText(/The invitation link for this mediation session has expired/i)).toBeInTheDocument();
      expect(screen.queryByTestId('download-receipt-btn')).not.toBeInTheDocument();
    });
  });

  describe('AbstentionWaiverModal', () => {
    it('filters out null/None/empty middle names from concatenated expected name', () => {
      mockStoreState.legal_first_name = 'Bob';
      mockStoreState.legal_middle_name = null;
      mockStoreState.legal_last_name = 'Melton';

      render(<AbstentionWaiverModal onClose={vi.fn()} />);

      // Text in quote box should have Bob Melton
      const quotes = screen.getAllByText((content, element) => {
        return element.tagName.toLowerCase() === 'strong' && content.includes('Bob Melton');
      });
      expect(quotes.length).toBeGreaterThan(0);
    });

    it('filters out string None or null middle names', () => {
      mockStoreState.legal_first_name = 'Bob';
      mockStoreState.legal_middle_name = 'None';
      mockStoreState.legal_last_name = 'Melton';

      render(<AbstentionWaiverModal onClose={vi.fn()} />);
      const quotes = screen.getAllByText((content, element) => {
        return element.tagName.toLowerCase() === 'strong' && content.includes('Bob Melton');
      });
      expect(quotes.length).toBeGreaterThan(0);
    });

    it('enables Sign & Abstain button only when typed signature matches exactly', async () => {
      mockStoreState.legal_first_name = 'Alice';
      mockStoreState.legal_middle_name = 'Marie';
      mockStoreState.legal_last_name = 'Smith';

      render(<AbstentionWaiverModal onClose={vi.fn()} />);

      const input = screen.getByTestId('signature-input');
      const submitBtn = screen.getByTestId('confirm-abstain-btn');

      expect(submitBtn).toBeDisabled();

      // Partially correct
      fireEvent.change(input, { target: { value: 'Alice Smith' } });
      expect(submitBtn).toBeDisabled();

      // Correct
      fireEvent.change(input, { target: { value: 'Alice Marie Smith' } });
      expect(submitBtn).not.toBeDisabled();

      // Click submits
      mockStoreState.abstainSession.mockResolvedValueOnce();
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(mockStoreState.abstainSession).toHaveBeenCalledWith('Alice Marie Smith');
      });
    });
  });

  describe('HeirValuationPanel', () => {
    it('displays unallocated points', () => {
      mockStoreState.unallocatedPoints = 450;
      render(<HeirValuationPanel />);

      expect(screen.getByTestId('unallocated-points-val')).toHaveTextContent('450');
      expect(screen.getByText(/Remaining points:/i)).toBeInTheDocument();
    });

    it('disables submit button if unallocatedPoints > 0', () => {
      mockStoreState.unallocatedPoints = 50;
      render(<HeirValuationPanel />);

      const submitBtn = screen.getByTestId('submit-valuations-btn');
      expect(submitBtn).toBeDisabled();
    });

    it('enables submit button if unallocatedPoints is 0 and not submitted', () => {
      mockStoreState.unallocatedPoints = 0;
      render(<HeirValuationPanel />);

      const submitBtn = screen.getByTestId('submit-valuations-btn');
      expect(submitBtn).not.toBeDisabled();
    });

    it('calls submitValuations when submit button is clicked', async () => {
      mockStoreState.unallocatedPoints = 0;
      mockStoreState.submitValuations.mockResolvedValueOnce();

      render(<HeirValuationPanel />);
      const submitBtn = screen.getByTestId('submit-valuations-btn');
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(mockStoreState.submitValuations).toHaveBeenCalled();
      });
    });

    it('opens AbstentionWaiverModal when abstain is clicked', () => {
      render(<HeirValuationPanel />);
      const abstainTrigger = screen.getByTestId('abstain-trigger-btn');

      expect(screen.queryByTestId('abstention-modal-backdrop')).not.toBeInTheDocument();

      fireEvent.click(abstainTrigger);

      expect(screen.getByTestId('abstention-modal-backdrop')).toBeInTheDocument();
    });

    it('displays inventory update warning banner when inventoryUpdatedNotice is present and allows dismissing it', async () => {
      mockStoreState.inventoryUpdatedNotice = 'Item "Antique Desk" was deleted.';
      render(<HeirValuationPanel />);

      const banner = screen.getByTestId('inventory-update-warning-banner');
      expect(banner).toBeInTheDocument();
      expect(screen.getByText(/Item "Antique Desk" was deleted/i)).toBeInTheDocument();
      expect(screen.getByText(/Your submission status has been reset/i)).toBeInTheDocument();

      const dismissBtn = screen.getByRole('button', { name: /Dismiss/i });
      fireEvent.click(dismissBtn);

      expect(useMediationStore.setState).toHaveBeenCalledWith({ inventoryUpdatedNotice: null });
    });
  });
});
