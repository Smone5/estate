/**
 * useSpeech — Web Speech API hook for the Estate Steward.
 *
 * Task T24: Wraps the browser's SpeechRecognition API
 * (webkitSpeechRecognition) with:
 *   - HTTPS / localhost secure context guard
 *   - Hold-to-talk (touchstart/touchend, mousedown/mouseup)
 *   - Click-to-toggle mode for desktop
 *   - Auto-silence timeout handling (onend cleanup)
 *   - InvalidStateError guard on fast permission clicks
 *   - AudioContext resume button ('Enable Audio') on dashboard mount
 *     per Frontend Spec §5.5
 *
 * Depends on T17 (Vite base), T23 (useWebSocket — the transcribed text
 * feeds into the WebSocket send pipeline).
 *
 * Returns:
 *   {
 *     transcript: string,            // accumulated transcribed text
 *     isListening: boolean,          // mic is active
 *     isSupported: boolean,          // browser supports SpeechRecognition
 *     isSecureContext: boolean,      // HTTPS or localhost
 *     micError: string | null,       // error message to display
 *     startListening: () => void,    // begin transcription
 *     stopListening: () => void,     // stop and finalize
 *     toggleListening: () => void,   // click-to-toggle
 *     showAudioContextButton: boolean, // AudioContext suspended
 *     resumeAudioContext: () => void,  // resume AudioContext on user gesture
 *   }
 */

import { useState, useRef, useCallback, useEffect } from 'react';

const SpeechRecognitionAPI =
  window.SpeechRecognition || window.webkitSpeechRecognition;

/**
 * Determine whether the current origin is a secure context for
 * Web Speech API access. Localhost is always treated as secure.
 */
function isSecureOrigin() {
  const protocol = window.location.protocol;
  if (protocol === 'https:') return true;
  const hostname = window.location.hostname;
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

export function useSpeech() {
  const [transcript, setTranscript] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [micError, setMicError] = useState(null);
  const [showAudioContextButton, setShowAudioContextButton] = useState(false);

  const recognitionRef = useRef(null);
  const isStartedRef = useRef(false);
  const isCancelledRef = useRef(false);
  const transcriptAccRef = useRef('');
  const audioContextRef = useRef(null);

  const isSupported = SpeechRecognitionAPI !== undefined;
  const isSecure = isSecureOrigin();

  // ── AudioContext Unlock (Frontend Spec §5.5) ─────────────────────────
  useEffect(() => {
    // Try to create and check AudioContext state
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;

      const ctx = new AudioCtx();
      audioContextRef.current = ctx;

      if (ctx.state === 'suspended') {
        setShowAudioContextButton(true);
      }

      // Clean up on unmount
      return () => {
        ctx.close().catch(() => {});
      };
    } catch {
      // AudioContext not available — no button needed
    }
  }, []);

  const resumeAudioContext = useCallback(() => {
    if (audioContextRef.current && audioContextRef.current.state === 'suspended') {
      audioContextRef.current.resume().then(() => {
        setShowAudioContextButton(false);
      }).catch(() => {
        // Resume failed — button stays visible
      });
    } else {
      setShowAudioContextButton(false);
    }
  }, []);

  // ── Initialize SpeechRecognition instance ────────────────────────────
  const getRecognition = useCallback(() => {
    if (!recognitionRef.current) {
      const rec = new SpeechRecognitionAPI();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = 'en-US';
      rec.maxAlternatives = 1;

      rec.onresult = (event) => {
        let interim = '';
        let final = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const result = event.results[i];
          if (result.isFinal) {
            final += result[0].transcript;
          } else {
            interim += result[0].transcript;
          }
        }

        // Accumulate final transcripts
        if (final) {
          transcriptAccRef.current += ' ' + final;
        }

        const display = (transcriptAccRef.current + ' ' + interim).trim();
        setTranscript(display);
      };

      rec.onerror = (event) => {
        // 'no-speech' and 'aborted' are normal — ignore them
        if (event.error === 'no-speech' || event.error === 'aborted') {
          return;
        }
        if (event.error === 'not-allowed') {
          setMicError('Microphone access denied. Please enable microphone permissions in your browser settings.');
        } else if (event.error === 'network') {
          setMicError('Network error during voice recognition. The speech service may be unavailable.');
        } else {
          setMicError(`Speech recognition error: ${event.error}`);
        }
        // Clean up state
        isStartedRef.current = false;
        setIsListening(false);
      };

      rec.onend = () => {
        // Browser auto-closed recognition (e.g., silent timeout on mobile)
        isStartedRef.current = false;
        setIsListening(false);
        // transcriptAccRef preserves the accumulated text
      };

      recognitionRef.current = rec;
    }
    return recognitionRef.current;
  }, []);

  // ── Start listening ──────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (!isSupported) {
      setMicError('Speech recognition is not supported in this browser.');
      return;
    }

    if (!isSecure) {
      setMicError('Voice input requires a secure HTTPS connection.');
      return;
    }

    setMicError(null);

    // Dismiss AudioContext button on first interaction
    if (showAudioContextButton) {
      resumeAudioContext();
    }

    const rec = getRecognition();
    if (isStartedRef.current) return; // already running

    try {
      rec.start();
      isStartedRef.current = true;
      isCancelledRef.current = false;
      setIsListening(true);
    } catch (err) {
      // InvalidStateError — recognition already started from a prior click
      // Ignore silently; state management handles it.
      if (err?.name === 'InvalidStateError') return;
      setMicError('Failed to start speech recognition.');
    }
  }, [isSupported, isSecure, showAudioContextButton, resumeAudioContext, getRecognition]);

  // ── Stop listening ───────────────────────────────────────────────────
  const stopListening = useCallback(() => {
    isCancelledRef.current = true;
    const rec = recognitionRef.current;
    if (!rec || !isStartedRef.current) return;

    try {
      rec.stop();
      isStartedRef.current = false;
      setIsListening(false);
    } catch (err) {
      // InvalidStateError — browser already stopped it (mobile auto-silence)
      // Just update the UI state; transcriptAccRef is preserved.
      if (err?.name === 'InvalidStateError') {
        isStartedRef.current = false;
        setIsListening(false);
        return;
      }
    }
  }, []);

  // ── Toggle (click-to-toggle for desktop) ─────────────────────────────
  const toggleListening = useCallback(() => {
    if (isListening) {
      stopListening();
    } else {
      // Reset transcript accumulator for a new recording session
      transcriptAccRef.current = '';
      setTranscript('');
      startListening();
    }
  }, [isListening, startListening, stopListening]);

  // ── Clear accumulated transcript ─────────────────────────────────────
  const clearTranscript = useCallback(() => {
    transcriptAccRef.current = '';
    setTranscript('');
  }, []);

  return {
    transcript,
    isListening,
    isSupported,
    isSecureContext: isSecure,
    micError,
    startListening,
    stopListening,
    toggleListening,
    clearTranscript,
    showAudioContextButton,
    resumeAudioContext,
  };
}