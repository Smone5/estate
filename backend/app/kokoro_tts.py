"""
Kokoro-82M ONNX Text-to-Speech Engine (T21)
============================================
Local CPU speech synthesis for the Estate Steward mediation agent.
Implements the graceful degradation contract: if model files are missing or
kokoro-onnx/onnxruntime cannot be imported, emits CRITICAL WARNING and
returns None for synthesize() calls (text-only chat proceeds).

Configurable via environment variables:
  KOKORO_MODEL_PATH  (default: app/models/kokoro-v1.0.onnx)
  KOKORO_VOICES_PATH (default: app/models/voices-v1.0.bin)
"""

import asyncio
import base64
import io
import logging
import os
from pathlib import Path
from typing import Optional

import soundfile as sf

logger = logging.getLogger(__name__)

# ── Lazy import guard for kokoro-onnx / onnxruntime ──────────────────────────
_KOKORO_AVAILABLE = False
_Kokoro = None
_ort = None

try:
    from kokoro_onnx import Kokoro as _KokoroClass
    import onnxruntime as _ort
    _Kokoro = _KokoroClass
    _KOKORO_AVAILABLE = True
except ImportError as exc:
    logger.warning(
        "Kokoro-82M TTS engine unavailable — onnxruntime/kokoro-onnx not installed "
        "on this platform. WebSocket audio chunks will be omitted. "
        "Text-only chat proceeds normally. (ImportError: %s)",
        exc,
    )


# ── Default paths ────────────────────────────────────────────────────────────
_MODELS_DIR = Path(__file__).resolve().parent / "models"

DEFAULT_MODEL_PATH = os.environ.get(
    "KOKORO_MODEL_PATH",
    str(_MODELS_DIR / "kokoro-v1.0.onnx"),
)
DEFAULT_VOICES_PATH = os.environ.get(
    "KOKORO_VOICES_PATH",
    str(_MODELS_DIR / "voices-v1.0.bin"),
)

# ONNX session options — restrict CPU threads per Backend Spec §7.1
_SESS_OPTIONS: dict = {}
if _ort is not None:
    _sess_opts = _ort.SessionOptions()
    _sess_opts.intra_op_num_threads = 2
    _sess_opts.inter_op_num_threads = 1
    _SESS_OPTIONS = {"session_options": _sess_opts}


class KokoroTTS:
    """
    Wrapper around the Kokoro-82M ONNX speech engine.

    Handles model file validation, graceful degradation, and async-safe
    serialization via an asyncio.Semaphore(1).
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
    ):
        self._model_path = model_path or DEFAULT_MODEL_PATH
        self._voices_path = voices_path or DEFAULT_VOICES_PATH
        self._engine: Optional[object] = None
        self._available: bool = False
        self._semaphore = asyncio.Semaphore(1)

        if not _KOKORO_AVAILABLE:
            logger.warning(
                "KokoroTTS: onnxruntime not available on this platform. "
                "TTS synthesis disabled."
            )
            return

        if not self._validate_model_files():
            logger.warning(
                "KokoroTTS: Model files missing or unreadable. "
                "model_path=%s exists=%s  voices_path=%s exists=%s — "
                "TTS synthesis disabled.",
                self._model_path,
                Path(self._model_path).exists(),
                self._voices_path,
                Path(self._voices_path).exists(),
            )
            return

        try:
            self._engine = _Kokoro(
                model_path=self._model_path,
                voices_path=self._voices_path,
                **_SESS_OPTIONS,
            )
            self._available = True
            logger.info(
                "KokoroTTS: Engine initialized successfully. "
                "model=%s voices=%s",
                self._model_path,
                self._voices_path,
            )
        except Exception as exc:
            logger.warning(
                "KokoroTTS: Engine initialization failed — %s. "
                "TTS synthesis disabled.",
                exc,
            )

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if the TTS engine is ready to synthesize audio."""
        return self._available

    def validate_model_files(self) -> bool:
        """Check that both model files exist and are readable on disk."""
        return self._validate_model_files()

    async def synthesize(
        self,
        text: str,
        voice: str = "af_bella",
        speed: float = 0.95,
    ) -> Optional[str]:
        """
        Synthesize text to a base64-encoded PCM_16 WAV string.

        Returns None if the engine is unavailable (degraded mode) or
        synthesis fails — callers must handle None.
        """
        if not self._available or self._engine is None:
            return None

        async with self._semaphore:
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None,
                    self._synthesize_sync,
                    text,
                    voice,
                    speed,
                )
            except Exception as exc:
                logger.error("KokoroTTS.synthesize failed: %s", exc)
                return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _validate_model_files(self) -> bool:
        model = Path(self._model_path)
        voices = Path(self._voices_path)
        return model.is_file() and voices.is_file()

    def _synthesize_sync(self, text: str, voice: str, speed: float) -> str:
        """Blocking synthesis call — runs inside run_in_executor."""
        samples, sample_rate = self._engine.create(
            text=text,
            voice=voice,
            speed=speed,
        )

        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, samples, sample_rate, format="WAV", subtype="PCM_16")
        wav_data = wav_buffer.getvalue()

        return base64.b64encode(wav_data).decode("utf-8")


# ── Module-level singleton (lazy init) ────────────────────────────────────────

_tts_instance: Optional[KokoroTTS] = None


def get_kokoro_tts() -> KokoroTTS:
    """Return the module-level KokoroTTS singleton, creating it on first call."""
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = KokoroTTS()
    return _tts_instance