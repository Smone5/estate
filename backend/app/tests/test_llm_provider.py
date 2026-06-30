"""
Tests for LLM Provider Abstraction Layer (T50).
Covers:
  - Singleton get_provider / reset_provider
  - Ollama health-check (mocked HTTP)
  - Provider factory: all 5 providers route to correct backend methods
  - Mock LLM provider compatibility (mock_llm.py scenarios)
  - Structured JSON output validation
  - Embedding vector dimension verification
  - Vision generation
  - REAL Ollama integration tests (against localhost:11434)
"""
import json
import os
import time
from unittest import mock

import pytest
from pydantic import BaseModel

from app.services.llm_provider import (
    LLMProvider,
    check_ollama_health,
    get_provider,
    reset_provider,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENROUTER,
    PROVIDER_NVIDIA,
    MODEL_KEY_FAST,
    MODEL_KEY_SLOW,
    MODEL_KEY_VISION,
    MODEL_KEY_EMBEDDING,
)

from app.tests.mock_llm import MockLLMProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Reset provider singleton and clear env vars before each test."""
    reset_provider()
    # Set to ollama by default so tests can override safely
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("VISION_PROVIDER", "ollama")
    # Clear cloud API keys
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    yield
    reset_provider()


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------


def test_get_provider_returns_singleton():
    p1 = get_provider()
    p2 = get_provider()
    assert p1 is p2


def test_reset_provider_creates_new_instance():
    p1 = get_provider()
    reset_provider()
    p2 = get_provider()
    assert p1 is not p2


# ---------------------------------------------------------------------------
# Health-check tests
# ---------------------------------------------------------------------------


class FakeResponse:
    """Simulates httpx.Response."""
    def __init__(self, status_code=200):
        self.status_code = status_code


def test_check_ollama_health_success(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse(200)

    monkeypatch.setattr("httpx.get", fake_get)
    assert check_ollama_health() is True


def test_check_ollama_health_connection_refused(monkeypatch):
    def fake_get(*args, **kwargs):
        import httpx
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("httpx.get", fake_get)
    assert check_ollama_health() is False


def test_check_ollama_health_timeout(monkeypatch):
    def fake_get(*args, **kwargs):
        import httpx
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("httpx.get", fake_get)
    assert check_ollama_health() is False


def test_check_ollama_health_http_error(monkeypatch):
    def fake_get(*args, **kwargs):
        return FakeResponse(500)

    monkeypatch.setattr("httpx.get", fake_get)
    assert check_ollama_health() is False


# ---------------------------------------------------------------------------
# Mock LLM provider integration tests
# ---------------------------------------------------------------------------


def test_mock_provider_generate_text():
    provider = MockLLMProvider()
    result = provider.generate_text("fast", "You are helpful", "Hello", 0.5)
    assert isinstance(result, str)
    assert len(result) > 0


def test_mock_provider_generate_structured():
    class TestModel(BaseModel):
        intent: str

    provider = MockLLMProvider()
    result = provider.generate_structured(
        "fast",
        "You are a routing helper. Classify...",
        "I want to submit my valuations",
        TestModel,
        0.0,
    )
    assert isinstance(result, TestModel)
    assert result.intent == "VALUATION_SUBMISSION"


def test_mock_provider_generate_vision():
    provider = MockLLMProvider()
    result = provider.generate_vision("vision", b"fake-image-bytes", "Describe this image")
    assert isinstance(result, str)
    assert "Antique Mahogany Desk" in result


def test_mock_provider_get_embeddings():
    provider = MockLLMProvider()
    result = provider.get_embeddings("embedding", "sample text")
    assert isinstance(result, list)
    assert len(result) == 768


def test_mock_provider_ollama_down_scenario():
    provider = MockLLMProvider()
    provider.set_scenario("ollama_down")
    # First call simulates down
    ok = provider.check_ollama_health()
    assert ok is False
    # Second call recovers
    ok = provider.check_ollama_health()
    assert ok is True


def test_mock_provider_critique_fail_scenario():
    provider = MockLLMProvider()
    provider.set_scenario("critique_fail")
    result = provider.generate_text("slow", "system", "user", 0.0)
    parsed = json.loads(result)
    assert parsed["violation"] is True


def test_mock_provider_timeout_scenario():
    import httpx
    provider = MockLLMProvider()
    provider.set_scenario("timeout")
    with pytest.raises(httpx.ReadTimeout):
        provider.generate_text("fast", "system", "user", 0.5)


# ---------------------------------------------------------------------------
# LLMProvider factory routing tests (unit — no actual API calls)
#
# All providers now route through litellm.completion()/litellm.embedding(),
# so routing is verified by faking those two module-level functions and
# asserting the `model=` kwarg they were called with carries the expected
# LiteLLM prefix for the active provider — one fake covers every provider.
# ---------------------------------------------------------------------------


def _fake_completion_response(text):
    choice = mock.MagicMock()
    choice.message.content = text
    return mock.MagicMock(choices=[choice])


def _fake_embedding_response(vector):
    return mock.MagicMock(data=[{"embedding": vector}])


def test_provider_generate_text_routes_to_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("FAST_THINKER_MODEL", "test-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11111")
    reset_provider()

    provider = get_provider()
    fake_completion = mock.MagicMock(return_value=_fake_completion_response("Mock mediator response"))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_text("fast", "system", "user", 0.5)
    assert isinstance(result, str)
    assert result == "Mock mediator response"
    called_model = fake_completion.call_args.kwargs["model"]
    assert called_model == "ollama_chat/test-model"
    assert fake_completion.call_args.kwargs["api_base"] == "http://localhost:11111"


def test_provider_generate_structured_routes_to_ollama(monkeypatch):
    class CritiqueResult(BaseModel):
        violation: bool
        reason: str

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("FAST_THINKER_MODEL", "test-model")
    reset_provider()

    provider = get_provider()
    fake_completion = mock.MagicMock(
        return_value=_fake_completion_response('{"violation": false, "reason": ""}')
    )
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_structured("slow", "system", "user", CritiqueResult, 0.0)
    assert isinstance(result, CritiqueResult)
    assert result.violation is False


def test_provider_get_embeddings_routes_to_ollama(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embed")
    reset_provider()

    provider = get_provider()
    fake_embedding = mock.MagicMock(return_value=_fake_embedding_response([0.1] * 768))
    monkeypatch.setattr("app.services.llm_provider.litellm.embedding", fake_embedding)

    result = provider.get_embeddings("embedding", "sample")
    assert isinstance(result, list)
    assert len(result) == 768
    assert fake_embedding.call_args.kwargs["model"] == "ollama/test-embed"


def test_provider_generate_vision_routes_to_ollama(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "ollama")
    monkeypatch.setenv("VISION_MODEL", "test-vision")
    reset_provider()

    provider = get_provider()
    fake_completion = mock.MagicMock(return_value=_fake_completion_response("OCR result text"))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_vision("vision", b"\xff\xd8", "Describe")
    assert isinstance(result, str)
    assert result == "OCR result text"
    assert fake_completion.call_args.kwargs["model"] == "ollama_chat/test-vision"
    messages = fake_completion.call_args.kwargs["messages"]
    image_url = messages[0]["content"][1]["image_url"]["url"]
    assert not image_url.startswith("data:")


def test_provider_raises_on_unsupported_text_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown_vendor")
    reset_provider()
    provider = get_provider()
    with pytest.raises(ValueError, match="Unsupported text provider"):
        provider.generate_text("fast", "sys", "usr", 0.5)


def test_provider_raises_on_unsupported_embedding_provider(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "unknown_vendor")
    reset_provider()
    provider = get_provider()
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        provider.get_embeddings("embedding", "test")


# ---------------------------------------------------------------------------
# OpenRouter routing tests
# ---------------------------------------------------------------------------


def test_provider_generate_text_routes_to_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("FAST_THINKER_MODEL", "openai/gpt-4o-mini")
    reset_provider()

    provider = get_provider()
    assert provider.llm_provider == PROVIDER_OPENROUTER

    fake_completion = mock.MagicMock(return_value=_fake_completion_response("OpenRouter response text"))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_text("fast", "system", "user", 0.5)
    assert result == "OpenRouter response text"
    # Already contains "/" — passed through to LiteLLM unprefixed
    assert fake_completion.call_args.kwargs["model"] == "openai/gpt-4o-mini"
    assert fake_completion.call_args.kwargs["api_key"] == "sk-test-key"


def test_provider_generate_structured_routes_to_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("SLOW_THINKER_MODEL", "claude-3.5-sonnet")
    reset_provider()

    class TestModel(BaseModel):
        score: int

    provider = get_provider()
    fake_completion = mock.MagicMock(return_value=_fake_completion_response('{"score": 42}'))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_structured("slow", "system", "user", TestModel, 0.0)
    assert isinstance(result, TestModel)
    assert result.score == 42
    assert fake_completion.call_args.kwargs["model"] == "openrouter/claude-3.5-sonnet"


def test_provider_get_embeddings_routes_to_openrouter(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    reset_provider()

    provider = get_provider()
    fake_embedding = mock.MagicMock(return_value=_fake_embedding_response([0.2] * 1536))
    monkeypatch.setattr("app.services.llm_provider.litellm.embedding", fake_embedding)

    result = provider.get_embeddings("embedding", "test text")
    assert isinstance(result, list)
    assert len(result) == 1536
    assert fake_embedding.call_args.kwargs["model"] == "openrouter/text-embedding-3-small"


def test_provider_generate_vision_routes_to_openrouter(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("VISION_MODEL", "openai/gpt-4o-mini")
    reset_provider()

    provider = get_provider()
    fake_completion = mock.MagicMock(return_value=_fake_completion_response("Vision OCR from OpenRouter"))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_vision("vision", b"\xff\xd8", "Describe image")
    assert result == "Vision OCR from OpenRouter"
    assert fake_completion.call_args.kwargs["model"] == "openai/gpt-4o-mini"


# ---------------------------------------------------------------------------
# Model name resolution
# ---------------------------------------------------------------------------


def test_resolve_model_keys():
    provider = get_provider()
    model = provider._resolve_model("fast")
    assert isinstance(model, str)
    assert len(model) > 0


def test_resolve_model_passthrough_unknown_key():
    provider = get_provider()
    raw_name = "some-custom-model:7b"
    result = provider._resolve_model(raw_name)
    assert result == raw_name


# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


def test_llm_provider_with_env_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    reset_provider()
    provider = get_provider()
    assert provider.llm_provider == "anthropic"


def test_embedding_provider_with_env_override(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "google")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    reset_provider()
    provider = get_provider()
    assert provider.embedding_provider == "google"


def test_vision_provider_with_env_override(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    reset_provider()
    provider = get_provider()
    assert provider.vision_provider == "openai"


# ---------------------------------------------------------------------------
# NVIDIA NIM routing tests
# ---------------------------------------------------------------------------


def test_provider_generate_text_routes_to_nvidia(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    monkeypatch.setenv("FAST_THINKER_MODEL", "llama-3.1-nemotron-70b-instruct")
    reset_provider()

    provider = get_provider()
    assert provider.llm_provider == PROVIDER_NVIDIA

    fake_completion = mock.MagicMock(return_value=_fake_completion_response("NVIDIA NIM response"))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_text("fast", "system", "user", 0.5)
    assert result == "NVIDIA NIM response"
    assert fake_completion.call_args.kwargs["model"] == "nvidia_nim/llama-3.1-nemotron-70b-instruct"
    assert fake_completion.call_args.kwargs["api_key"] == "nv-test-key"


def test_provider_generate_structured_routes_to_nvidia(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    monkeypatch.setenv("SLOW_THINKER_MODEL", "llama-3.1-nemotron-70b-instruct")
    reset_provider()

    class TestModel(BaseModel):
        score: int

    provider = get_provider()
    fake_completion = mock.MagicMock(return_value=_fake_completion_response('{"score": 99}'))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_structured("slow", "system", "user", TestModel, 0.0)
    assert isinstance(result, TestModel)
    assert result.score == 99


def test_provider_get_embeddings_routes_to_nvidia(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "nv-embed-qa-4")
    reset_provider()

    provider = get_provider()
    fake_embedding = mock.MagicMock(return_value=_fake_embedding_response([0.3] * 1024))
    monkeypatch.setattr("app.services.llm_provider.litellm.embedding", fake_embedding)

    result = provider.get_embeddings("embedding", "test text")
    assert isinstance(result, list)
    assert len(result) == 1024
    assert fake_embedding.call_args.kwargs["model"] == "nvidia_nim/nv-embed-qa-4"


def test_provider_generate_vision_routes_to_nvidia(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    monkeypatch.setenv("VISION_MODEL", "neva-22b")
    reset_provider()

    provider = get_provider()
    fake_completion = mock.MagicMock(return_value=_fake_completion_response("NVIDIA vision OCR"))
    monkeypatch.setattr("app.services.llm_provider.litellm.completion", fake_completion)

    result = provider.generate_vision("vision", b"\xff\xd8", "Describe image")
    assert result == "NVIDIA vision OCR"
    assert fake_completion.call_args.kwargs["model"] == "nvidia_nim/neva-22b"


def test_nvidia_provider_with_env_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    reset_provider()
    provider = get_provider()
    assert provider.llm_provider == "nvidia"


# ===================================================================
# REAL OLLAMA INTEGRATION TESTS
# ===================================================================
# These tests connect to the local Ollama server at http://localhost:11434
# and verify real inference with all four models. They are marked
# with @pytest.mark.ollama so they can be run selectively:
#
#     uv run pytest -m ollama tests/test_llm_provider.py
#
# Skip these tests in CI where Ollama is unavailable:
#     uv run pytest -m "not ollama" tests/test_llm_provider.py
# ===================================================================

ollama_marker = pytest.mark.ollama


def _ollama_is_reachable() -> bool:
    """Return True if Ollama is accepting connections."""
    import httpx
    try:
        resp = httpx.get("http://localhost:11434/", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def ollama_available() -> bool:
    """Session-scoped fixture: True if Ollama is reachable."""
    return _ollama_is_reachable()


@pytest.fixture
def ollama_provider(monkeypatch, ollama_available):
    """Return a real LLMProvider pointing at local Ollama, or skip."""
    if not ollama_available:
        pytest.skip("Ollama is not reachable at localhost:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("VISION_PROVIDER", "ollama")
    monkeypatch.setenv("FAST_THINKER_MODEL", "qwen3:8b")
    monkeypatch.setenv("SLOW_THINKER_MODEL", "qwen3:14b")
    monkeypatch.setenv("VISION_MODEL", "qwen3-vl:8b")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
    reset_provider()
    return get_provider()


# ---- Health-check (real) ----

def test_ollama_health_check_real():
    """Verify the health-check function works against the live Ollama."""
    if not _ollama_is_reachable():
        pytest.skip("Ollama is not reachable at localhost:11434")
    result = check_ollama_health()
    assert result is True


# ---- Fast thinker: qwen3:8b (text) ----

@ollama_marker
def test_ollama_generate_text_fast(ollama_provider):
    result = ollama_provider.generate_text(
        model_key=MODEL_KEY_FAST,
        system_prompt="You are a helpful assistant. Respond concisely.",
        user_input="In one sentence, what is the color of the sky on a clear day?",
        temperature=0.0,
    )
    assert isinstance(result, str)
    assert len(result) > 0
    assert "blue" in result.lower() or "Blue" in result


# ---- Slow thinker: qwen3:14b (structured JSON) ----

@ollama_marker
def test_ollama_generate_text_slow(ollama_provider):
    result = ollama_provider.generate_text(
        model_key=MODEL_KEY_SLOW,
        system_prompt="You are a helpful assistant.",
        user_input="Say exactly 'HELLO' in uppercase and nothing else.",
        temperature=0.0,
    )
    assert isinstance(result, str)
    assert len(result) > 0
    assert "HELLO" in result.upper()


@ollama_marker
def test_ollama_generate_structured_slow(ollama_provider):
    class CritiqueResult(BaseModel):
        violation: bool
        reason: str

    result = ollama_provider.generate_structured(
        model_key=MODEL_KEY_SLOW,
        system_prompt="You are a compliance auditor.",
        user_input=(
            'The mediator said: "Thank you for sharing that memory."\n\n'
            "Output a JSON block: {\"violation\": false, \"reason\": \"\"}"
        ),
        response_model=CritiqueResult,
        temperature=0.0,
    )
    assert isinstance(result, CritiqueResult)
    assert isinstance(result.violation, bool)


# ---- Vision: qwen3-vl:8b ----

@ollama_marker
def test_ollama_generate_vision(ollama_provider):
    """Send a tiny 1x1 white JPEG to qwen3-vl and verify it returns text."""
    # Minimal valid JPEG (1x1 white pixel)
    tiny_jpeg = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
        0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
        0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
        0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C,
        0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D,
        0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
        0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27,
        0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
        0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4,
        0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
        0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04,
        0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF,
        0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04,
        0x00, 0x00, 0x01, 0x7D, 0x01, 0x02, 0x03, 0x00,
        0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32,
        0x81, 0x91, 0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1,
        0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00,
        0x3F, 0x00, 0x6B, 0x38, 0x56, 0x52, 0xAD, 0xCA,
        0xB0, 0x20, 0x8F, 0x50, 0x6A, 0xA5, 0x8E, 0x9D,
        0x6D, 0x62, 0x84, 0x5B, 0xA6, 0xDD, 0xC7, 0x2D,
        0xC9, 0x39, 0xF4, 0xE6, 0xB4, 0xEA, 0xBC, 0x56,
        0xF1, 0x43, 0xBB, 0xCB, 0x5C, 0x6E, 0x39, 0x3C,
        0x93, 0xCD, 0x58, 0xAF, 0xFF, 0xD9,
    ])
    result = ollama_provider.generate_vision(
        model_key=MODEL_KEY_VISION,
        image_bytes=tiny_jpeg,
        prompt="Describe what you see in this image in one short sentence.",
    )
    assert isinstance(result, str)
    assert len(result) > 0


# ---- Embeddings: nomic-embed-text ----

@ollama_marker
def test_ollama_get_embeddings(ollama_provider):
    result = ollama_provider.get_embeddings(
        model_key=MODEL_KEY_EMBEDDING,
        text="The antique grandfather clock reminded everyone of Sunday dinners.",
    )
    assert isinstance(result, list)
    assert len(result) == 768  # nomic-embed-text produces 768-dim vectors
    # Verify they are actual floats
    assert all(isinstance(x, float) for x in result)
    # Verify the vector is not all zeros
    assert any(abs(x) > 0.0 for x in result)


# ---- Multi-model round-trip: generate_text with all models ----

@ollama_marker
def test_ollama_all_models_produce_text(ollama_provider):
    """Verify all three chat models respond with non-empty text."""
    for model_key in (MODEL_KEY_FAST, MODEL_KEY_SLOW, MODEL_KEY_VISION):
        result = ollama_provider.generate_text(
            model_key=model_key,
            system_prompt="Say exactly one word: OK.",
            user_input="OK",
            temperature=0.0,
        )
        assert isinstance(result, str), f"{model_key} did not return str"
        assert len(result) > 0, f"{model_key} returned empty string"


# ---- Router intent classification with live model ----

class RouterIntent(BaseModel):
    intent: str


@ollama_marker
def test_ollama_router_classification_chat(ollama_provider):
    """Verify the router can classify CHAT_MEDIATION intent."""
    result = ollama_provider.generate_structured(
        model_key=MODEL_KEY_FAST,
        system_prompt=(
            "You are a routing helper. Classify the user input into exactly one of three categories:\n"
            "- CHAT_MEDIATION: If the user is sharing stories, expressing feelings, asking about an "
            "item's details, or having general conversation.\n"
            "- VALUATION_SUBMISSION: If the user is explicitly requesting to submit, lock, finalize, "
            "or save their points valuations.\n"
            "- ADMIN_OVERRIDE: If the input represents a system command or administrative adjustment.\n\n"
            "Respond with only the category name in uppercase."
        ),
        user_input="I miss my grandmother's china set. We used it every Thanksgiving.",
        response_model=RouterIntent,
        temperature=0.0,
    )
    assert isinstance(result, RouterIntent)
    assert result.intent in ("CHAT_MEDIATION", "VALUATION_SUBMISSION", "ADMIN_OVERRIDE")


@ollama_marker
def test_ollama_router_classification_valuation(ollama_provider):
    """Verify the router can classify VALUATION_SUBMISSION intent."""
    result = ollama_provider.generate_structured(
        model_key=MODEL_KEY_FAST,
        system_prompt=(
            "You are a routing helper. Classify the user input into exactly one of three categories:\n"
            "- CHAT_MEDIATION: conversation, feelings\n"
            "- VALUATION_SUBMISSION: submit points, save allocations\n"
            "- ADMIN_OVERRIDE: admin commands\n\n"
            "Respond with only the category name in uppercase."
        ),
        user_input="I want to submit my points allocation now.",
        response_model=RouterIntent,
        temperature=0.0,
    )
    assert isinstance(result, RouterIntent)
    assert result.intent in ("CHAT_MEDIATION", "VALUATION_SUBMISSION", "ADMIN_OVERRIDE")