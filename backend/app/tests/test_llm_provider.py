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
"""
import json
import os
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
    assert result.intent == "CHAT_MEDIATION"


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
# ---------------------------------------------------------------------------

class FakeOllamaResponse:
    """Simulates ollama.ChatResponse."""
    def __init__(self, text):
        self.response = text


class FakeOllamaEmbedResponse:
    def __init__(self, vector):
        self.embeddings = vector


def _fake_ollama_client():
    """Build a mock ollama client that returns canned responses."""
    client = mock.MagicMock()
    # Default response for generate_text
    client.generate.return_value = FakeOllamaResponse("Mock mediator response")
    client.embed.return_value = mock.MagicMock()
    client.embed.return_value.get.return_value = [[0.1] * 768]
    return client


def _fake_ollama_client_structured():
    """Build a mock ollama client that returns structured JSON."""
    client = mock.MagicMock()
    client.generate.return_value = FakeOllamaResponse('{"violation": false, "reason": ""}')
    client.embed.return_value = mock.MagicMock()
    client.embed.return_value.get.return_value = [[0.1] * 768]
    return client


def test_provider_generate_text_routes_to_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("FAST_THINKER_MODEL", "test-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11111")
    reset_provider()

    provider = get_provider()
    provider._ollama_client = _fake_ollama_client()

    result = provider.generate_text("fast", "system", "user", 0.5)
    assert isinstance(result, str)
    assert result == "Mock mediator response"


def test_provider_generate_structured_routes_to_ollama(monkeypatch):
    class CritiqueResult(BaseModel):
        violation: bool
        reason: str

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("FAST_THINKER_MODEL", "test-model")
    reset_provider()

    provider = get_provider()
    provider._ollama_client = _fake_ollama_client_structured()

    result = provider.generate_structured("slow", "system", "user", CritiqueResult, 0.0)
    assert isinstance(result, CritiqueResult)
    assert result.violation is False


def test_provider_get_embeddings_routes_to_ollama(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embed")
    reset_provider()

    provider = get_provider()
    provider._ollama_client = _fake_ollama_client()

    result = provider.get_embeddings("embedding", "sample")
    assert isinstance(result, list)
    assert len(result) == 768


def test_provider_generate_vision_routes_to_ollama(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "ollama")
    monkeypatch.setenv("VISION_MODEL", "test-vision")
    reset_provider()

    provider = get_provider()
    client = _fake_ollama_client()
    client.generate.return_value = FakeOllamaResponse("OCR result text")
    provider._ollama_client = client

    result = provider.generate_vision("vision", b"\xff\xd8", "Describe")
    assert isinstance(result, str)
    assert result == "OCR result text"


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

    # Mock the OpenAI client used by OpenRouter
    mock_openai_client = mock.MagicMock()
    mock_choice = mock.MagicMock()
    mock_choice.message.content = "OpenRouter response text"
    mock_openai_client.chat.completions.create.return_value = mock.MagicMock(
        choices=[mock_choice]
    )
    provider._openrouter_client = mock_openai_client

    result = provider.generate_text("fast", "system", "user", 0.5)
    assert result == "OpenRouter response text"


def test_provider_generate_structured_routes_to_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("SLOW_THINKER_MODEL", "anthropic/claude-3.5-sonnet")
    reset_provider()

    class TestModel(BaseModel):
        score: int

    provider = get_provider()
    mock_openai_client = mock.MagicMock()
    mock_choice = mock.MagicMock()
    mock_choice.message.content = '{"score": 42}'
    mock_openai_client.chat.completions.create.return_value = mock.MagicMock(
        choices=[mock_choice]
    )
    provider._openrouter_client = mock_openai_client

    result = provider.generate_structured("slow", "system", "user", TestModel, 0.0)
    assert isinstance(result, TestModel)
    assert result.score == 42


def test_provider_get_embeddings_routes_to_openrouter(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    reset_provider()

    provider = get_provider()
    mock_openai_client = mock.MagicMock()
    mock_embed_data = mock.MagicMock()
    mock_embed_data.embedding = [0.2] * 1536
    mock_openai_client.embeddings.create.return_value = mock.MagicMock(
        data=[mock_embed_data]
    )
    provider._openrouter_client = mock_openai_client

    result = provider.get_embeddings("embedding", "test text")
    assert isinstance(result, list)
    assert len(result) == 1536


def test_provider_generate_vision_routes_to_openrouter(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-key")
    monkeypatch.setenv("VISION_MODEL", "openai/gpt-4o-mini")
    reset_provider()

    provider = get_provider()
    mock_openai_client = mock.MagicMock()
    mock_choice = mock.MagicMock()
    mock_choice.message.content = "Vision OCR from OpenRouter"
    mock_openai_client.chat.completions.create.return_value = mock.MagicMock(
        choices=[mock_choice]
    )
    provider._openrouter_client = mock_openai_client

    result = provider.generate_vision("vision", b"\xff\xd8", "Describe image")
    assert result == "Vision OCR from OpenRouter"


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
    monkeypatch.setenv("FAST_THINKER_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct")
    reset_provider()

    provider = get_provider()
    assert provider.llm_provider == PROVIDER_NVIDIA

    mock_client = mock.MagicMock()
    mock_choice = mock.MagicMock()
    mock_choice.message.content = "NVIDIA NIM response"
    mock_client.chat.completions.create.return_value = mock.MagicMock(
        choices=[mock_choice]
    )
    provider._nvidia_client = mock_client

    result = provider.generate_text("fast", "system", "user", 0.5)
    assert result == "NVIDIA NIM response"


def test_provider_generate_structured_routes_to_nvidia(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    monkeypatch.setenv("SLOW_THINKER_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct")
    reset_provider()

    class TestModel(BaseModel):
        score: int

    provider = get_provider()
    mock_client = mock.MagicMock()
    mock_choice = mock.MagicMock()
    mock_choice.message.content = '{"score": 99}'
    mock_client.chat.completions.create.return_value = mock.MagicMock(
        choices=[mock_choice]
    )
    provider._nvidia_client = mock_client

    result = provider.generate_structured("slow", "system", "user", TestModel, 0.0)
    assert isinstance(result, TestModel)
    assert result.score == 99


def test_provider_get_embeddings_routes_to_nvidia(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "nvidia/nv-embed-qa-4")
    reset_provider()

    provider = get_provider()
    mock_client = mock.MagicMock()
    mock_embed_data = mock.MagicMock()
    mock_embed_data.embedding = [0.3] * 1024
    mock_client.embeddings.create.return_value = mock.MagicMock(
        data=[mock_embed_data]
    )
    provider._nvidia_client = mock_client

    result = provider.get_embeddings("embedding", "test text")
    assert isinstance(result, list)
    assert len(result) == 1024


def test_provider_generate_vision_routes_to_nvidia(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    monkeypatch.setenv("VISION_MODEL", "nvidia/neva-22b")
    reset_provider()

    provider = get_provider()
    mock_client = mock.MagicMock()
    mock_choice = mock.MagicMock()
    mock_choice.message.content = "NVIDIA vision OCR"
    mock_client.chat.completions.create.return_value = mock.MagicMock(
        choices=[mock_choice]
    )
    provider._nvidia_client = mock_client

    result = provider.generate_vision("vision", b"\xff\xd8", "Describe image")
    assert result == "NVIDIA vision OCR"


def test_nvidia_provider_with_env_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test-key")
    reset_provider()
    provider = get_provider()
    assert provider.llm_provider == "nvidia"
