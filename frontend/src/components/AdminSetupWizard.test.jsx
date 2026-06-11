// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import AdminSetupWizard from './AdminSetupWizard';
import '@testing-library/jest-dom';

describe('AdminSetupWizard Component', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── Step 1: Credentials Form ────────────────────────────────────────────
  it('renders the first-time setup form', () => {
    render(<AdminSetupWizard />);

    expect(screen.getByText('First-Time Administrator Setup')).toBeInTheDocument();
    expect(screen.getByTestId('setup-creds-form')).toBeInTheDocument();
    expect(screen.getByTestId('setup-username-input')).toBeInTheDocument();
    expect(screen.getByTestId('setup-password-input')).toBeInTheDocument();
    expect(screen.getByTestId('setup-submit-btn')).toBeInTheDocument();
  });

  it('shows validation error when username is empty', async () => {
    render(<AdminSetupWizard />);

    fireEvent.submit(screen.getByTestId('setup-creds-form'));

    await waitFor(() => {
      expect(
        screen.getByText('Username and password are required.'),
      ).toBeInTheDocument();
    });
  });

  it('shows validation error when password is too short', async () => {
    render(<AdminSetupWizard />);

    fireEvent.change(screen.getByTestId('setup-username-input'), {
      target: { value: 'admin' },
    });
    fireEvent.change(screen.getByTestId('setup-password-input'), {
      target: { value: '123' },
    });
    fireEvent.submit(screen.getByTestId('setup-creds-form'));

    await waitFor(() => {
      expect(
        screen.getByText('Password must be at least 8 characters.'),
      ).toBeInTheDocument();
    });
  });

  it('submits valid credentials and transitions to mnemonic screen', async () => {
    const mockMnemonic = [
      'abandon', 'ability', 'able', 'about', 'above', 'absent',
      'absorb', 'abstract', 'absurd', 'abuse', 'access', 'accident',
      'account', 'accuse', 'achieve', 'acid', 'acoustic', 'acquire',
      'across', 'act', 'action', 'actor', 'actress', 'actual',
    ];

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ mnemonic: mockMnemonic }),
    });

    render(<AdminSetupWizard />);

    fireEvent.change(screen.getByTestId('setup-username-input'), {
      target: { value: 'executor' },
    });
    fireEvent.change(screen.getByTestId('setup-password-input'), {
      target: { value: 'secure-password-123' },
    });
    fireEvent.submit(screen.getByTestId('setup-creds-form'));

    await waitFor(() => {
      expect(screen.getByTestId('bip39-mnemonic-screen')).toBeInTheDocument();
    });

    // Verify the first word is displayed
    expect(screen.getByText('abandon')).toBeInTheDocument();
  });

  it('handles mnemonic as a space-separated string', async () => {
    const mnemonicStr = 'abandon ability able about above absent absorb abstract absurd abuse access accident account accuse achieve acid acoustic acquire across act action actor actress actual';

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ mnemonic: mnemonicStr }),
    });

    render(<AdminSetupWizard />);

    fireEvent.change(screen.getByTestId('setup-username-input'), {
      target: { value: 'admin' },
    });
    fireEvent.change(screen.getByTestId('setup-password-input'), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByTestId('setup-creds-form'));

    await waitFor(() => {
      expect(screen.getByTestId('bip39-mnemonic-screen')).toBeInTheDocument();
      expect(screen.getByText('abandon')).toBeInTheDocument();
    });
  });

  it('displays API error banner on failed setup', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Admin account already exists' }),
      status: 400,
    });

    render(<AdminSetupWizard />);

    fireEvent.change(screen.getByTestId('setup-username-input'), {
      target: { value: 'admin' },
    });
    fireEvent.change(screen.getByTestId('setup-password-input'), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByTestId('setup-creds-form'));

    await waitFor(() => {
      expect(
        screen.getByText('Admin account already exists'),
      ).toBeInTheDocument();
    });
  });

  // ── Step 2: Mnemonic Confirmation → Setup Complete ──────────────────────
  it('transitions to setup complete after mnemonic confirmation', async () => {
    const mockMnemonic = [
      'abandon', 'ability', 'able', 'about', 'above', 'absent',
      'absorb', 'abstract', 'absurd', 'abuse', 'access', 'accident',
      'account', 'accuse', 'achieve', 'acid', 'acoustic', 'acquire',
      'across', 'act', 'action', 'actor', 'actress', 'actual',
    ];

    const onSetupComplete = vi.fn();

    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ mnemonic: mockMnemonic }),
    });

    render(<AdminSetupWizard onSetupComplete={onSetupComplete} />);

    fireEvent.change(screen.getByTestId('setup-username-input'), {
      target: { value: 'admin' },
    });
    fireEvent.change(screen.getByTestId('setup-password-input'), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByTestId('setup-creds-form'));

    await waitFor(() => {
      expect(screen.getByTestId('bip39-mnemonic-screen')).toBeInTheDocument();
    });

    // Check the confirmation checkbox
    fireEvent.click(screen.getByTestId('mnemonic-confirm-checkbox'));
    // Click proceed
    fireEvent.click(screen.getByTestId('mnemonic-proceed-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('setup-complete')).toBeInTheDocument();
      expect(screen.getByText('Setup Complete')).toBeInTheDocument();
      expect(onSetupComplete).toHaveBeenCalledTimes(1);
    });
  });

  it('shows loading state on submit button while API is in flight', async () => {
    // Never resolve to keep loading state
    global.fetch.mockImplementationOnce(() => new Promise(() => {}));

    render(<AdminSetupWizard />);

    fireEvent.change(screen.getByTestId('setup-username-input'), {
      target: { value: 'admin' },
    });
    fireEvent.change(screen.getByTestId('setup-password-input'), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByTestId('setup-creds-form'));

    await waitFor(() => {
      expect(screen.getByText('Creating Account...')).toBeInTheDocument();
    });
  });
});