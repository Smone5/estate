"""
Local Whisper Speech-to-Text Engine (T47)
==========================================
Local CPU speech recognition for the Estate Steward heir chat voice input.
Implements the same graceful degradation contract as kokoro_tts.py: if the
model can't load or faster-whisper/ctranslate2 isn't installed, emits a
WARNING and returns None for transcribe() calls (text chat still works;
the client falls back to typing).

Configurable via environment variables:
  WHISPER_MODEL_SIZE  (default: base.en)
  WHISPER_MODEL_PATH  (default: app/models/whisper — local cache/snapshot dir)
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Lazy import guard for faster-whisper ─────────────────────────────────────
_WHISPER_AVAILABLE = False
_WhisperModel = None

try:
    from faster_whisper import WhisperModel as _WhisperModelClass
    _WhisperModel = _WhisperModelClass
    _WHISPER_AVAILABLE = True
except ImportError as exc:
    logger.warning(
        "Whisper STT engine unavailable — faster-whisper not installed "
        "on this platform. Live voice input will be omitted; heirs can "
        "still type. (ImportError: %s)",
        exc,
    )

# NOTE: deliberately NOT under app/models — docker-compose mounts that path
# as a host volume (for the large Kokoro weights) which would shadow a
# baked-in Whisper model with an empty host directory.
_DEFAULT_WHISPER_DIR = Path(__file__).resolve().parent.parent / "whisper_models"

DEFAULT_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base.en")
DEFAULT_MODEL_PATH = os.environ.get(
    "WHISPER_MODEL_PATH",
    str(_DEFAULT_WHISPER_DIR),
)


class WhisperSTT:
    """
    Wrapper around the local faster-whisper engine.

    Handles model load validation, graceful degradation, and async-safe
    serialization via an asyncio.Semaphore(1) (CPU inference is not
    safely shared across concurrent calls on a single model instance).
    """

    def __init__(self, model_size: Optional[str] = None, download_root: Optional[str] = None):
        self._model_size = model_size or DEFAULT_MODEL_SIZE
        self._download_root = download_root or DEFAULT_MODEL_PATH
        self._engine: Optional[object] = None
        self._available: bool = False
        self._semaphore = asyncio.Semaphore(1)

        if not _WHISPER_AVAILABLE:
            logger.warning(
                "WhisperSTT: faster-whisper not available on this platform. "
                "STT disabled."
            )
            return

        try:
            Path(self._download_root).mkdir(parents=True, exist_ok=True)
            self._engine = _WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
                download_root=self._download_root,
                cpu_threads=2,
            )
            self._available = True
            logger.info(
                "WhisperSTT: Engine initialized successfully. model=%s",
                self._model_size,
            )
        except Exception as exc:
            logger.warning(
                "WhisperSTT: Engine initialization failed — %s. STT disabled.",
                exc,
            )

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if the STT engine is ready to transcribe audio."""
        return self._available

    async def transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """
        Transcribe raw audio bytes (any container faster-whisper/ffmpeg
        can decode, e.g. WAV/WebM/Ogg) to text.

        Returns None if the engine is unavailable (degraded mode) or
        transcription fails — callers must handle None.
        """
        if not self._available or self._engine is None:
            return None

        async with self._semaphore:
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None,
                    self._transcribe_sync,
                    audio_bytes,
                )
            except Exception as exc:
                logger.error("WhisperSTT.transcribe failed: %s", exc)
                return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        """Blocking transcription call — runs inside run_in_executor."""
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as tmp:
            tmp.write(audio_bytes)
            tmp.flush()
            segments, _info = self._engine.transcribe(
                tmp.name,
                language="en",
                vad_filter=True,
            )
            return "".join(segment.text for segment in segments).strip()


# ── Module-level singleton (lazy init) ────────────────────────────────────────

_stt_instance: Optional[WhisperSTT] = None


def get_whisper_stt() -> WhisperSTT:
    """Return the module-level WhisperSTT singleton, creating it on first call."""
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = WhisperSTT()
    return _stt_instance
