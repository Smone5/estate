import { useState, useEffect, useRef, useCallback } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useSpeech } from '../hooks/useSpeech';
import { useAudioPlayback } from '../hooks/useAudioPlayback';

/**
 * HeirAssistantPanel — Chat surface for the AI Mediator with voice input/output.
 *
 * Wires the heir dashboard to the existing /ws chat_message <-> chat_reply_chunk
 * contract (see backend main.py T22 websocket endpoint). Voice is layered on
 * top of the Phase 1 text chat: useSpeech (T24) transcribes mic input into the
 * same input box, and useAudioPlayback (T25) plays back Kokoro-synthesized
 * audio chunks as they stream in. Both gracefully degrade to text-only when
 * unsupported (no SpeechRecognition, insecure origin, or Kokoro unavailable
 * server-side) — nothing here requires voice to function.
 */
export default function HeirAssistantPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const [inputText, setInputText] = useState('');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [voiceMuted, setVoiceMuted] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);

  const sessionId = useMediationStore((s) => s.session_id);
  const messages = useMediationStore((s) => s.messages);
  const addMessage = useMediationStore((s) => s.addMessage);
  const loadChatHistory = useMediationStore((s) => s.loadChatHistory);
  const sessionStatus = useMediationStore((s) => s.sessionStatus);
  const userStatus = useMediationStore((s) => s.userStatus);
  const isPaused = useMediationStore((s) => s.isPaused);
  const is_hitl_suspended = useMediationStore((s) => s.is_hitl_suspended);

  const { send } = useWebSocket();
  const scrollRef = useRef(null);

  const {
    isRecording,
    isSupported: isSpeechSupported,
    micError,
    startRecording,
    stopRecording,
    showAudioContextButton,
    resumeAudioContext,
  } = useSpeech();

  const { isPlaying, isSyntheticPlaying } = useAudioPlayback(voiceMuted);

  // Mirrors the disableChat gate computed in DashboardGuard (Frontend Spec §5.4)
  const chatDisabled =
    sessionStatus === 'SETUP' ||
    sessionStatus === 'LOCKED' ||
    userStatus === 'PROFILE_HOLD' ||
    isPaused ||
    is_hitl_suspended;

  useEffect(() => {
    if (!isOpen || !sessionId || historyLoaded) return;
    let cancelled = false;
    loadChatHistory()
      .catch((err) => console.error('Failed to load chat history', err))
      .finally(() => {
        if (!cancelled) setHistoryLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, sessionId, historyLoaded, loadChatHistory]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen]);

  // Clear the "Transcribing..." state once a new message lands — subscribed
  // (not selected) so setIsTranscribing runs inside the subscription
  // callback rather than synchronously in the effect body.
  useEffect(() => {
    let prevCount = useMediationStore.getState().messages.length;
    const unsubscribe = useMediationStore.subscribe((state) => {
      if (state.messages.length > prevCount) {
        prevCount = state.messages.length;
        setIsTranscribing(false);
      }
    });
    return unsubscribe;
  }, []);

  // Mic toggle: start begins recording locally; stop sends the recorded
  // clip to the backend for local Whisper transcription (T47) — the
  // transcript + mediator reply both arrive over the WebSocket.
  const handleMicToggle = useCallback(async () => {
    if (isRecording) {
      const blob = await stopRecording();
      if (!blob || blob.size === 0 || chatDisabled) return;

      setIsTranscribing(true);
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64 = reader.result.split(',')[1] || '';
        if (base64) {
          send({ type: 'voice_message', audio: base64 });
        } else {
          setIsTranscribing(false);
        }
      };
      reader.onerror = () => setIsTranscribing(false);
      reader.readAsDataURL(blob);
    } else {
      startRecording();
    }
  }, [isRecording, stopRecording, startRecording, send, chatDisabled]);

  const handleSend = useCallback(() => {
    const text = inputText.trim();
    if (!text || chatDisabled) return;

    send({ type: 'chat_message', text });
    addMessage({ sender: 'HEIR', text });
    setInputText('');
  }, [inputText, chatDisabled, send, addMessage]);

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      <button
        className="assistant-fab"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label={isOpen ? 'Close AI Mediator chat' : 'Open AI Mediator chat'}
        data-testid="assistant-fab"
      >
        {isOpen ? '✕' : '💬'}
      </button>

      {isOpen && (
        <>
          <div
            className="help-drawer-backdrop"
            onClick={() => setIsOpen(false)}
            data-testid="assistant-backdrop"
          />
          <div className="help-drawer assistant-drawer" role="dialog" aria-modal="true" data-testid="assistant-panel">
            <div className="help-drawer-header">
              <h3 style={{ fontFamily: 'var(--font-serif)', margin: 0 }}>AI Mediator</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)' }}>
                <button
                  className="close-btn"
                  onClick={() => setVoiceMuted((prev) => !prev)}
                  aria-label={voiceMuted ? 'Unmute voice replies' : 'Mute voice replies'}
                  aria-pressed={voiceMuted}
                  data-testid="assistant-mute-btn"
                  title={voiceMuted ? 'Voice replies muted' : 'Voice replies on'}
                >
                  {voiceMuted ? '🔇' : '🔊'}
                </button>
                <button className="close-btn" onClick={() => setIsOpen(false)} aria-label="Close chat">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                  </svg>
                </button>
              </div>
            </div>

            {isPlaying && isSyntheticPlaying && (
              <div className="banner banner-info" style={{ borderRadius: 0, margin: 0, fontSize: '0.8rem', padding: 'var(--space-xs) var(--space-md)' }}>
                Synthesized AI Voice — playing reply
              </div>
            )}

            <div className="assistant-messages" ref={scrollRef} data-testid="assistant-messages">
              {messages.length === 0 ? (
                <p className="text-sm text-muted" style={{ padding: 'var(--space-sm)', fontStyle: 'italic' }}>
                  Ask about an item's history, your point allocations, or anything else on your mind.
                  This conversation is confidential to you. Tap the microphone to speak instead of typing.
                </p>
              ) : (
                messages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`assistant-message ${msg.sender === 'HEIR' ? 'assistant-message-self' : 'assistant-message-agent'}`}
                  >
                    {msg.text}
                  </div>
                ))
              )}
            </div>

            <div className="assistant-input-row">
              {chatDisabled ? (
                <p className="text-xs text-muted" style={{ margin: 0, padding: 'var(--space-sm) 0' }}>
                  Mediation chat is currently locked.
                </p>
              ) : (
                <>
                  {showAudioContextButton && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={resumeAudioContext}
                      data-testid="assistant-enable-audio-btn"
                      style={{ flexShrink: 0 }}
                    >
                      Enable Audio
                    </button>
                  )}

                  {isSpeechSupported && (
                    <button
                      type="button"
                      className={`assistant-mic-btn ${isRecording ? 'assistant-mic-btn-active' : ''}`}
                      onClick={handleMicToggle}
                      disabled={isTranscribing}
                      aria-label={isRecording ? 'Stop voice input' : 'Start voice input'}
                      aria-pressed={isRecording}
                      data-testid="assistant-mic-btn"
                    >
                      {isRecording ? '⏹' : '🎤'}
                    </button>
                  )}

                  <textarea
                    className="assistant-input"
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={
                      isRecording
                        ? 'Recording... tap stop when done'
                        : isTranscribing
                        ? 'Transcribing...'
                        : 'Type a message...'
                    }
                    rows={1}
                    readOnly={isRecording || isTranscribing}
                    data-testid="assistant-input"
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleSend}
                    disabled={isRecording || isTranscribing || !inputText.trim()}
                    data-testid="assistant-send-btn"
                  >
                    Send
                  </button>
                </>
              )}
            </div>

            {micError && (
              <p className="text-xs" style={{ color: 'var(--color-error)', margin: 0, padding: '0 var(--space-lg) var(--space-sm)' }}>
                {micError}
              </p>
            )}
          </div>
        </>
      )}
    </>
  );
}
