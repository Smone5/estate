// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import AdminInspectIDModal from './AdminInspectIDModal';
import '@testing-library/jest-dom';

describe('AdminInspectIDModal Component', () => {
  const mockHeir = {
    id: 'heir-1',
    legal_first_name: 'Alice',
    legal_middle_name: 'Marie',
    legal_last_name: 'Smith',
    date_of_birth: '1990-05-15',
    relationship_to_decedent: 'Daughter',
    username: 'alice_smith',
    email: 'alice@example.com',
    phone: '+1 555-1234',
    physical_address: '123 Main St, Anytown',
    identity_verified: false,
    id_scan_uri: '/uploads/scan.jpg',
  };

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders nothing when heir is null', () => {
    const { container } = render(<AdminInspectIDModal heir={null} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders split-pane with ID scan and legal details', () => {
    render(<AdminInspectIDModal heir={mockHeir} onClose={() => {}} />);

    expect(screen.getByText('Inspect Beneficiary Identity')).toBeInTheDocument();
    expect(screen.getByTestId('id-scan-pane')).toBeInTheDocument();
    expect(screen.getByTestId('legal-details-pane')).toBeInTheDocument();
    expect(screen.getByTestId('id-scan-image')).toBeInTheDocument();
    expect(screen.getByTestId('approve-identity-btn')).toBeInTheDocument();
    expect(screen.getByTestId('reject-trigger-btn')).toBeInTheDocument();
  });

  it('shows "No ID scan uploaded" when id_scan_uri is null', () => {
    render(
      <AdminInspectIDModal
        heir={{ ...mockHeir, id_scan_uri: null }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText('No ID scan uploaded')).toBeInTheDocument();
    expect(screen.queryByTestId('id-scan-image')).not.toBeInTheDocument();
  });

  it('displays legal name correctly with middle name', () => {
    render(<AdminInspectIDModal heir={mockHeir} onClose={() => {}} />);
    expect(screen.getByText('Alice Marie Smith')).toBeInTheDocument();
  });

  it('displays legal name without null middle name', () => {
    render(
      <AdminInspectIDModal
        heir={{ ...mockHeir, legal_middle_name: null }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText('Alice Smith')).toBeInTheDocument();
  });

  it('calls approve API and closes on success', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const onClose = vi.fn();
    const onVerificationComplete = vi.fn();

    render(
      <AdminInspectIDModal
        heir={mockHeir}
        onClose={onClose}
        onVerificationComplete={onVerificationComplete}
      />,
    );

    fireEvent.click(screen.getByTestId('approve-identity-btn'));

    await waitFor(() => {
      expect(onVerificationComplete).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('shows rejection form when Reject & Flag is clicked', () => {
    render(<AdminInspectIDModal heir={mockHeir} onClose={() => {}} />);

    fireEvent.click(screen.getByTestId('reject-trigger-btn'));

    expect(screen.getByTestId('rejection-reason-textarea')).toBeInTheDocument();
    expect(screen.getByTestId('reject-confirm-btn')).toBeInTheDocument();
  });

  it('rejects with reason and calls API', async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    const onClose = vi.fn();

    render(<AdminInspectIDModal heir={mockHeir} onClose={onClose} />);

    fireEvent.click(screen.getByTestId('reject-trigger-btn'));

    fireEvent.change(screen.getByTestId('rejection-reason-textarea'), {
      target: { value: 'Name mismatch' },
    });

    fireEvent.click(screen.getByTestId('reject-confirm-btn'));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('requires rejection reason before submitting', async () => {
    render(<AdminInspectIDModal heir={mockHeir} onClose={() => {}} />);

    fireEvent.click(screen.getByTestId('reject-trigger-btn'));

    const rejectBtn = screen.getByTestId('reject-confirm-btn');

    // Button should be disabled when no reason
    expect(rejectBtn).toBeDisabled();

    fireEvent.change(screen.getByTestId('rejection-reason-textarea'), {
      target: { value: '  ' },
    });

    // Whitespace-only should still be disabled
    expect(rejectBtn).toBeDisabled();
  });

  it('calls onClose when cancel is clicked', () => {
    const onClose = vi.fn();
    render(<AdminInspectIDModal heir={mockHeir} onClose={onClose} />);

    fireEvent.click(screen.getByTestId('inspect-id-cancel-btn'));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('displays API error on failed approve', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Server error' }),
      status: 500,
    });

    render(<AdminInspectIDModal heir={mockHeir} onClose={() => {}} />);

    fireEvent.click(screen.getByTestId('approve-identity-btn'));

    await waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument();
    });
  });
});