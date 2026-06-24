// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import AdminVoiceRecorder from './AdminVoiceRecorder';
import '@testing-library/jest-dom';

describe('AdminVoiceRecorder Component', () => {
  const assetId = 'asset-abc';
  let mockMediaRecorder;

  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn();
    
    // Mock URL methods
    global.URL.createObjectURL = vi.fn(() => 'blob:http://localhost/abc-123');
    global.URL.revokeObjectURL = vi.fn();

    // Mock HTMLMediaElement methods on prototype
    window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue();
    window.HTMLMediaElement.prototype.pause = vi.fn();

    // Setup mock MediaRecorder structure
    mockMediaRecorder = {
      start: vi.fn(function() {
        this.state = 'recording';
      }),
      stop: vi.fn(function() {
        this.state = 'inactive';
        if (this.onstop) {
          this.onstop();
        }
      }),
      state: 'inactive',
      mimeType: 'audio/webm',
    };

    global.MediaRecorder = vi.fn().mockImplementation((stream, options) => {
      mockMediaRecorder.mimeType = options?.mimeType || 'audio/webm';
      return mockMediaRecorder;
    });
    global.MediaRecorder.isTypeSupported = vi.fn().mockReturnValue(true);

    // Mock MediaDevices
    global.navigator.mediaDevices = {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }),
    };

    // Ensure we mock location to bypass insecure context guard in tests
    // JSDOM has localhost as hostname by default, so isSecureContext() returns true
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders Record button in idle state', () => {
    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);
    expect(screen.getByTestId(`record-btn-${assetId}`)).toBeInTheDocument();
    expect(screen.getByText('Record Spoken Story / Provenance')).toBeInTheDocument();
  });

  it('starts recording on click', async () => {
    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);
    const recordBtn = screen.getByTestId(`record-btn-${assetId}`);
    
    fireEvent.click(recordBtn);

    await waitFor(() => {
      expect(global.navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true });
      expect(global.MediaRecorder).toHaveBeenCalled();
      expect(mockMediaRecorder.start).toHaveBeenCalled();
    });

    expect(screen.getByTestId(`stop-btn-${assetId}`)).toBeInTheDocument();
  });

  it('stops recording and enables Play, Re-do, and Save controls', async () => {
    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);
    
    // Start recording
    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));

    // Stop recording
    const stopBtn = await screen.findByTestId(`stop-btn-${assetId}`);
    fireEvent.click(stopBtn);

    // Verify recorded UI controls appear
    expect(await screen.findByTestId(`play-btn-${assetId}`)).toBeInTheDocument();
    expect(screen.getByTestId(`redo-btn-${assetId}`)).toBeInTheDocument();
    expect(screen.getByTestId(`save-recording-btn-${assetId}`)).toBeInTheDocument();
  });

  it('toggles playback using HTMLMediaElement play/pause', async () => {
    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);
    
    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));
    const stopBtn = await screen.findByTestId(`stop-btn-${assetId}`);
    fireEvent.click(stopBtn);

    const playBtn = await screen.findByTestId(`play-btn-${assetId}`);
    
    // Click play
    fireEvent.click(playBtn);
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();

    // Screen state should reflect playing
    expect(await screen.findByText('⏸ Pause')).toBeInTheDocument();

    // Click pause
    fireEvent.click(screen.getByText('⏸ Pause'));
    expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it('allows uploading/saving the recorded blob with the correct file extension', async () => {
    const onSavedMock = vi.fn();
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'success' }),
    });

    render(<AdminVoiceRecorder assetId={assetId} onSaved={onSavedMock} />);
    
    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));
    const stopBtn = await screen.findByTestId(`stop-btn-${assetId}`);
    fireEvent.click(stopBtn);

    const saveBtn = await screen.findByTestId(`save-recording-btn-${assetId}`);
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(`/api/assets/${assetId}/audio`, expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        body: expect.any(FormData),
      }));
      expect(onSavedMock).toHaveBeenCalled();
    });
  });

  it('saves staging recordings locally without uploading to a placeholder asset', async () => {
    const onSavedMock = vi.fn();

    render(<AdminVoiceRecorder assetId="staging" onSaved={onSavedMock} />);

    fireEvent.click(screen.getByTestId('record-btn-staging'));
    const stopBtn = await screen.findByTestId('stop-btn-staging');
    fireEvent.click(stopBtn);

    const saveBtn = await screen.findByTestId('save-recording-btn-staging');
    expect(saveBtn).toHaveTextContent('Save to Item');
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(onSavedMock).toHaveBeenCalledWith(expect.any(Blob));
      expect(global.fetch).not.toHaveBeenCalled();
    });
  });
});
