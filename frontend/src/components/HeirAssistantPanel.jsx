import { useState, useEffect, useRef, useCallback } from 'react';
import { useMediationStore } from '../store/useMediationStore';
import { useWebSocket } from '../hooks/useWebSocket';
import { useSpeech } from '../hooks/useSpeech';
import { useAudioPlayback } from '../hooks/useAudioPlayback';

/**
 * HeirAssistantPanel — Chat surface for the AI Mediator with voice input/output.
 *
 * Wires the heir dashboard to the existing /ws chat_message <-> chat_reply_chunk
 * contract (see backend main.py T22 websocket endpoint). Per Backend Spec
 * §5 (Voice Transcription Ingestion), speech recognition runs entirely
 * client-side via the Web Speech API (useSpeech/T24) to keep the Pi 5 host
 * lightweight — transcribed text is sent as a normal chat_message with
 * metadata.input_method: "voice", processed identically to typed text.
 * useAudioPlayback (T25) plays back Kokoro-synthesized audio chunks as they
 * stream in. Both gracefully degrade to text-only when unsupported (no
 * SpeechRecognition, insecure origin, or Kokoro unavailable server-side) —
 * nothing here requires voice to function.
 */
export default function HeirAssistantPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const [inputText, setInputText] = useState('');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [voiceMuted, setVoiceMuted] = useState(false);

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
    transcript,
    isListening,
    isSupported: isSpeechSupported,
    isSecureContext,
    micError,
    startListening,
    stopListening,
    clearTranscript,
    showAudioContextButton,
    resumeAudioContext,
  } = useSpeech();

  const { isPlaying, isSyntheticPlaying } = useAudioPlayback(voiceMuted);
  const wasListeningRef = useRef(false);

  // Mirrors the disableChat gate computed in DashboardGuard (Frontend Spec §5.4).
  // Unlike sliders/justification inputs, chat stays open during SETUP so heirs
  // can ask general/support questions before the session is launched.
  const chatDisabled =
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

  // Mirror the live transcript into the input box while the mic is held,
  // per specs_frontend.md hold-to-talk UX (same pattern as the gallery
  // voice search bar).
  useEffect(() => {
    if (isListening) {
      setInputText(transcript);
    }
  }, [transcript, isListening]);

  // On mic release (isListening true -> false), send the finalized
  // transcript as a normal chat_message per Backend Spec §5 (Voice
  // Transcription Ingestion): recognition is entirely client-side, and the
  // transcribed text is packaged with metadata.input_method: "voice" and
  // processed identically to typed chat by the existing /ws pipeline.
  useEffect(() => {
    if (wasListeningRef.current && !isListening) {
      const text = transcript.trim();
      if (text && !chatDisabled) {
        send({ type: 'chat_message', text, metadata: { input_method: 'voice' } });
        addMessage({ sender: 'HEIR', text });
      }
      setInputText('');
      clearTranscript();
    }
    wasListeningRef.current = isListening;
  }, [isListening, transcript, chatDisabled, send, addMessage, clearTranscript]);

  // Hold-to-talk: press starts client-side transcription, release stops it
  // and (via the effect above) sends the transcript. Mirrors AdminVoiceRecorder's
  // secure-context guard — startListening itself also refuses on insecure origins.
  const handleMicDown = useCallback(
    (e) => {
      if (e.cancelable) e.preventDefault();
      if (chatDisabled || !isSecureContext) return;
      clearTranscript();
      setInputText('');
      startListening();
    },
    [chatDisabled, isSecureContext, clearTranscript, startListening],
  );

  const handleMicUp = useCallback(() => {
    stopListening();
  }, [stopListening]);

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
                      className={`assistant-mic-btn ${isListening ? 'assistant-mic-btn-active' : ''}`}
                      onMouseDown={handleMicDown}
                      onMouseUp={handleMicUp}
                      onMouseLeave={() => isListening && handleMicUp()}
                      onTouchStart={handleMicDown}
                      onTouchEnd={handleMicUp}
                      onTouchCancel={handleMicUp}
                      disabled={!isSecureContext}
                      aria-label={isListening ? 'Release to send voice message' : 'Hold to speak'}
                      aria-pressed={isListening}
                      data-testid="assistant-mic-btn"
                    >
                      {isListening ? '⏹' : '🎤'}
                    </button>
                  )}

                  <textarea
                    className="assistant-input"
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={isListening ? 'Listening... release to send' : 'Type a message...'}
                    rows={1}
                    readOnly={isListening}
                    data-testid="assistant-input"
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleSend}
                    disabled={isListening || !inputText.trim()}
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
