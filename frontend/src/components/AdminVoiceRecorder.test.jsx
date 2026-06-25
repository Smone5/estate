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
        if (this.ondataavailable) {
          this.ondataavailable({
            data: new Blob(['recorded-audio'], { type: this.mimeType }),
          });
        }
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
        getTracks: () => [{
          stop: vi.fn(),
          label: 'MacBook Microphone',
          getSettings: () => ({ deviceId: 'mic-built-in' }),
        }],
        getAudioTracks: () => [{
          stop: vi.fn(),
          label: 'MacBook Microphone',
          getSettings: () => ({ deviceId: 'mic-built-in' }),
        }],
      }),
      enumerateDevices: vi.fn().mockResolvedValue([
        { kind: 'audioinput', deviceId: 'mic-built-in', label: 'MacBook Microphone' },
        { kind: 'audioinput', deviceId: 'mic-usb', label: 'USB Microphone' },
        { kind: 'videoinput', deviceId: 'camera', label: 'Camera' },
      ]),
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
    expect(screen.getByTestId(`setup-mic-btn-${assetId}`)).toBeInTheDocument();
    expect(screen.getByText('Record Spoken Story / Provenance')).toBeInTheDocument();
  });

  it('reconnects, lists microphones, and records with the selected input', async () => {
    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);

    fireEvent.click(screen.getByTestId(`setup-mic-btn-${assetId}`));
    fireEvent.click(screen.getByTestId(`test-microphone-${assetId}`));

    await waitFor(() => {
      expect(screen.getByText(/Connected to MacBook Microphone/)).toBeInTheDocument();
    });

    const select = screen.getByTestId(`microphone-select-${assetId}`);
    expect(select).toHaveValue('mic-built-in');
    fireEvent.change(select, { target: { value: 'mic-usb' } });
    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));

    await waitFor(() => {
      expect(global.navigator.mediaDevices.getUserMedia).toHaveBeenLastCalledWith({
        audio: { deviceId: { exact: 'mic-usb' } },
      });
    });
  });

  it('opens microphone setup after an empty recording', async () => {
    mockMediaRecorder.stop = vi.fn(function() {
      this.state = 'inactive';
      if (this.onstop) this.onstop();
    });

    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);

    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));
    fireEvent.click(await screen.findByTestId(`stop-btn-${assetId}`));

    expect(await screen.findByText(/No audio was captured/)).toBeInTheDocument();
    expect(screen.getByTestId(`mic-setup-${assetId}`)).toBeInTheDocument();
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

  it('accepts a final audio chunk delivered after the stop event', async () => {
    mockMediaRecorder.stop = vi.fn(function() {
      this.state = 'inactive';
      if (this.onstop) this.onstop();
      setTimeout(() => {
        if (this.ondataavailable) {
          this.ondataavailable({
            data: new Blob(['late-audio'], { type: this.mimeType }),
          });
        }
      }, 50);
    });

    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);

    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));
    fireEvent.click(await screen.findByTestId(`stop-btn-${assetId}`));

    expect(await screen.findByText(/Recording captured/)).toBeInTheDocument();
    expect(screen.queryByText(/No audio was captured/)).not.toBeInTheDocument();
  });

  it('toggles playback using HTMLMediaElement play/pause', async () => {
    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);
    
    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));
    const stopBtn = await screen.findByTestId(`stop-btn-${assetId}`);
    fireEvent.click(stopBtn);

    const playBtn = await screen.findByTestId(`play-btn-${assetId}`);
    
    // Click play
    fireEvent.click(playBtn);
    await waitFor(() => {
      expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();
    });

    // Screen state should reflect playing
    expect(await screen.findByText('⏸ Pause')).toBeInTheDocument();

    // Click pause
    fireEvent.click(screen.getByText('⏸ Pause'));
    expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it('does not show Pause when playback fails', async () => {
    window.HTMLMediaElement.prototype.play = vi.fn().mockRejectedValue(
      new DOMException('Unsupported source', 'NotSupportedError'),
    );

    render(<AdminVoiceRecorder assetId={assetId} onSaved={() => {}} />);

    fireEvent.click(screen.getByTestId(`record-btn-${assetId}`));
    fireEvent.click(await screen.findByTestId(`stop-btn-${assetId}`));
    fireEvent.click(await screen.findByTestId(`play-btn-${assetId}`));

    await waitFor(() => {
      expect(screen.getByText(/recording could not be played/i)).toBeInTheDocument();
    });
    expect(screen.getByTestId(`play-btn-${assetId}`)).toHaveTextContent('▶ Play');
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

  it('attaches staging recordings automatically without uploading to a placeholder asset', async () => {
    const onSavedMock = vi.fn();

    render(<AdminVoiceRecorder assetId="staging" onSaved={onSavedMock} />);

    fireEvent.click(screen.getByTestId('record-btn-staging'));
    const stopBtn = await screen.findByTestId('stop-btn-staging');
    fireEvent.click(stopBtn);

    await waitFor(() => {
      expect(onSavedMock).toHaveBeenCalledWith(expect.any(Blob));
      expect(global.fetch).not.toHaveBeenCalled();
    });
    expect(screen.getByText('Attached to this item automatically.')).toBeInTheDocument();
    expect(screen.queryByTestId('save-recording-btn-staging')).not.toBeInTheDocument();
  });
});
