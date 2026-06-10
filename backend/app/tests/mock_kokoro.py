"""
Mock Kokoro TTS Synthesizer (T21 — CI/CD Offline Test Wrapper)
================================================================
Drop-in replacement for the Kokoro ONNX speech engine that returns
pre-generated silent WAV buffers — zero ONNX model loading, zero CPU.

Usage in tests:
    from app.tests.mock_kokoro import MockKokoroTTS
    tts = MockKokoroTTS()
    b64_audio = tts.synthesize("Hello, I'm listening.")
"""

import io
import base64
import struct
import wave


def _silent_wav_base64(duration_sec: float = 1.0, sample_rate: int = 24000) -> str:
    """Generate a silent PCM_16 WAV and return as base64 string."""
    num_samples = int(sample_rate * duration_sec)
    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{num_samples}h", *([0] * num_samples)))
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class MockKokoroTTS:
    """
    Offline mock for the Kokoro-82M ONNX speech engine.
    Returns silent WAV buffers — tests run in <1ms with no model loading.
    """

    def __init__(self, model_path: str = "", voices_path: str = ""):
        self._model_path = model_path
        self._voices_path = voices_path
        self._synthesize_calls: list[dict] = []
        self._model_files_exist = True  # Simulate startup validation pass

    def set_model_files_missing(self):
        """Simulate the startup scenario where model files are absent."""
        self._model_files_exist = False

    def validate_model_files(self) -> bool:
        return self._model_files_exist

    def synthesize(self, text: str, voice: str = "af_bella", speed: float = 0.95) -> str:
        """
        Synthesize text to base64-encoded WAV.
        Returns a silent WAV buffer — no actual TTS processing.
        """
        self._synthesize_calls.append({
            "text": text,
            "voice": voice,
            "speed": speed,
        })
        duration = max(0.5, min(5.0, len(text) * 0.05))
        return _silent_wav_base64(duration_sec=duration)