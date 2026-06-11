"""
Tests for app/kokoro_tts.py — Kokoro-82M TTS Engine (T21)

Covers:
  - Model file validation (both present, one missing, both missing)
  - Degraded mode when model files are absent
  - Synthesize returns None when unavailable
  - Singleton pattern (get_kokoro_tts)
  - Interface parity with MockKokoroTTS
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.kokoro_tts import KokoroTTS, get_kokoro_tts, _tts_instance as _global_instance
from app.tests.mock_kokoro import MockKokoroTTS


# ──────────────────────────────────────────────────────────────────────────────
# Model file validation
# ──────────────────────────────────────────────────────────────────────────────

def test_validate_model_files_both_present(tmp_path):
    """validate_model_files returns True when both files exist."""
    model_file = tmp_path / "kokoro-v1.0.onnx"
    voices_file = tmp_path / "voices-v1.0.bin"
    model_file.write_text("dummy")
    voices_file.write_text("dummy")

    tts = KokoroTTS(model_path=str(model_file), voices_path=str(voices_file))
    result = tts.validate_model_files()
    assert result is True


def test_validate_model_files_model_missing():
    """validate_model_files returns False when model file is absent."""
    tts = KokoroTTS(
        model_path="/nonexistent/kokoro-v1.0.onnx",
        voices_path="/nonexistent/voices-v1.0.bin",
    )
    result = tts.validate_model_files()
    assert result is False


def test_validate_model_files_voices_missing(tmp_path):
    """validate_model_files returns False when voices file is absent."""
    model_file = tmp_path / "kokoro-v1.0.onnx"
    model_file.write_text("dummy")

    tts = KokoroTTS(
        model_path=str(model_file),
        voices_path="/nonexistent/voices-v1.0.bin",
    )
    result = tts.validate_model_files()
    assert result is False


# ──────────────────────────────────────────────────────────────────────────────
# Degraded mode — missing model files
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synthesize_returns_none_when_model_files_missing():
    """synthesize() returns None when model files are absent (degraded mode)."""
    tts = KokoroTTS(
        model_path="/nonexistent/kokoro-v1.0.onnx",
        voices_path="/nonexistent/voices-v1.0.bin",
    )
    assert tts.available is False

    result = await tts.synthesize("Hello, I am listening.")
    assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────

def test_get_kokoro_tts_singleton():
    """get_kokoro_tts() returns the same instance on repeated calls."""
    # Reset global singleton for clean test
    import app.kokoro_tts as ktts
    ktts._tts_instance = None

    instance_a = get_kokoro_tts()
    instance_b = get_kokoro_tts()
    assert instance_a is instance_b


# ──────────────────────────────────────────────────────────────────────────────
# Interface parity with MockKokoroTTS
# ──────────────────────────────────────────────────────────────────────────────

def test_mock_has_same_public_api():
    """MockKokoroTTS mirrors the KokoroTTS public interface."""
    real_api = {"validate_model_files", "synthesize"}
    mock_api = {
        name for name in dir(MockKokoroTTS)
        if not name.startswith("_") and callable(getattr(MockKokoroTTS, name, None))
    }
    for method in real_api:
        assert method in mock_api, f"MockKokoroTTS missing method: {method}"


def test_mock_validate_model_files_defaults_true():
    """MockKokoroTTS.validate_model_files() returns True by default."""
    mock = MockKokoroTTS()
    assert mock.validate_model_files() is True


def test_mock_validate_model_files_when_missing():
    """MockKokoroTTS.validate_model_files() returns False when set_missing."""
    mock = MockKokoroTTS()
    mock.set_model_files_missing()
    assert mock.validate_model_files() is False


def test_mock_synthesize_returns_base64_string():
    """MockKokoroTTS.synthesize() returns a base64 string."""
    mock = MockKokoroTTS()
    result = mock.synthesize("Hello, I am listening.")
    assert isinstance(result, str)
    assert len(result) > 0
    # Should be valid base64 (no decode errors)
    import base64
    decoded = base64.b64decode(result)
    assert len(decoded) > 0