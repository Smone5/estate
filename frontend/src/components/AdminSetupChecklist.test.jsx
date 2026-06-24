// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import AdminSetupChecklist from './AdminSetupChecklist';
import { useMediationStore } from '../store/useMediationStore';
import '@testing-library/jest-dom';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('AdminSetupChecklist Component', () => {
  const sessionId = 'session-123';
  let mockStoreState;

  beforeEach(() => {
    mockStoreState = {
      loadSessionDetails: vi.fn().mockResolvedValue({}),
    };

    useMediationStore.mockImplementation((selector) => {
      if (typeof selector === 'function') {
        return selector(mockStoreState);
      }
      return mockStoreState;
    });

    global.fetch = vi.fn();
    // Mock scrollIntoView
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders progress as 0% when heirs and assets are empty', () => {
    render(<AdminSetupChecklist sessionId={sessionId} heirs={[]} assets={[]} />);
    expect(screen.getByText('0% Complete')).toBeInTheDocument();
    expect(screen.getByText('⏳ Action Required')).toBeInTheDocument();
    expect(screen.getByText('⏳ Empty')).toBeInTheDocument();
    expect(screen.getByTestId('checklist-launch-btn')).toBeDisabled();
  });

  it('renders heirs step as completed when heirs are present', () => {
    const heirs = [{ id: 'h1', username: 'Alice' }];
    render(<AdminSetupChecklist sessionId={sessionId} heirs={heirs} assets={[]} />);
    expect(screen.getByText('50% Complete')).toBeInTheDocument();
    expect(screen.getByText('✅ Registered')).toBeInTheDocument();
  });

  it('renders assets step as completed when keepsakes are published and staged count is 0', () => {
    const assets = [{ id: 'a1', status: 'LIVE' }];
    render(<AdminSetupChecklist sessionId={sessionId} heirs={[]} assets={assets} />);
    expect(screen.getByText('50% Complete')).toBeInTheDocument();
    expect(screen.getByText('✅ Cataloged')).toBeInTheDocument();
    expect(screen.getByTestId('checklist-launch-btn')).toBeEnabled();
  });

  it('renders assets step as publish drafts when staged keepsakes exist', () => {
    const assets = [
      { id: 'a1', status: 'LIVE' },
      { id: 'a2', status: 'STAGED' },
    ];
    render(<AdminSetupChecklist sessionId={sessionId} heirs={[]} assets={assets} />);
    expect(screen.getByText('0% Complete')).toBeInTheDocument();
    expect(screen.getByText('⚠️ Publish Drafts')).toBeInTheDocument();
    // Launch button is enabled because we have at least 1 published keepsake
    expect(screen.getByTestId('checklist-launch-btn')).toBeEnabled();
  });

  it('navigates to heirs and upload sections when buttons are clicked', async () => {
    const divHeir = document.createElement('div');
    divHeir.id = 'register-heir-section';
    const divUpload = document.createElement('div');
    divUpload.id = 'upload-asset-section';
    document.body.appendChild(divHeir);
    document.body.appendChild(divUpload);

    const onNavigateToTab = vi.fn();
    render(
      <AdminSetupChecklist
        sessionId={sessionId}
        heirs={[]}
        assets={[]}
        onNavigateToTab={onNavigateToTab}
      />
    );

    fireEvent.click(screen.getByTestId('checklist-goto-heirs-btn'));
    expect(onNavigateToTab).toHaveBeenCalledWith('heirs');
    await waitFor(() => {
      expect(divHeir.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    });

    fireEvent.click(screen.getByTestId('checklist-goto-upload-btn'));
    expect(onNavigateToTab).toHaveBeenCalledWith('catalog');
    await waitFor(() => {
      expect(divUpload.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    });

    document.body.removeChild(divHeir);
    document.body.removeChild(divUpload);
  });

  it('calls launch API and loads session details on launch confirmation', async () => {
    window.confirm = vi.fn(() => true);
    global.fetch.mockResolvedValueOnce({ ok: true });
    const onLaunchMock = vi.fn();

    const assets = [{ id: 'a1', status: 'LIVE' }];

    render(
      <AdminSetupChecklist
        sessionId={sessionId}
        heirs={[]}
        assets={assets}
        onLaunch={onLaunchMock}
      />
    );

    const launchBtn = screen.getByTestId('checklist-launch-btn');
    expect(launchBtn).toBeEnabled();

    fireEvent.click(launchBtn);

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(`/api/sessions/${sessionId}/launch`, {
        method: 'POST',
        credentials: 'same-origin',
      });
      expect(mockStoreState.loadSessionDetails).toHaveBeenCalled();
      expect(onLaunchMock).toHaveBeenCalled();
    });
  });
});
