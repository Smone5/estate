"""
Test suite for GET /api/system/models — California AB 2013 transparency endpoint.

Per Compliance Spec §2.4:
- Returns metadata for all 5 AI components
- Dynamically reflects environment variable overrides
- Public access (no auth required)
- Each model entry includes component, name, parameters, license, provenance
"""

import os
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_env_overrides():
    """Remove env overrides before and after each test so tests don't leak."""
    overrides = ["FAST_THINKER_MODEL", "SLOW_THINKER_MODEL", "VISION_MODEL", "EMBEDDING_MODEL"]
    saved = {}
    for key in overrides:
        saved[key] = os.environ.pop(key, None)
    yield
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]


def test_system_models_returns_all_five_components():
    """Verify the endpoint returns exactly 5 model entries with all required fields."""
    response = client.get("/api/system/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    models = data["models"]
    assert len(models) == 5

    expected_components = [
        "Fast Mediator (System 1)",
        "Slow Critic (System 2)",
        "Vision OCR Engine",
        "Local Speech Synthesis (TTS)",
        "Semantic Search & RAG Embedding Engine",
    ]
    component_names = [m["component"] for m in models]
    assert component_names == expected_components

    for model in models:
        assert "component" in model
        assert "name" in model
        assert "parameters" in model
        assert "license" in model
        assert "provenance" in model


def test_system_models_default_names():
    """Without env overrides, the endpoint returns default model names."""
    response = client.get("/api/system/models")
    assert response.status_code == 200
    models = response.json()["models"]

    fast = models[0]
    slow = models[1]
    vision = models[2]
    embedding = models[4]

    assert "Qwen-2.5" in fast["name"]
    assert "Qwen-2.5" in slow["name"] or "14B" in slow["name"]
    assert "Llava" in vision["name"] or "llava" in vision["name"].lower()
    assert "nomic-embed-text" in embedding["name"].lower()


def test_system_models_dynamic_fast_thinker():
    """Setting FAST_THINKER_MODEL env var changes the Fast Mediator entry."""
    os.environ["FAST_THINKER_MODEL"] = "qwen2.5:3b-instruct"
    response = client.get("/api/system/models")
    assert response.status_code == 200
    models = response.json()["models"]
    fast = models[0]
    assert "3.1B" in fast["parameters"]
    assert "Pi 5" in fast["name"]
    assert fast["name"] != "Qwen-2.5-8B-Instruct"


def test_system_models_dynamic_slow_thinker():
    """Setting SLOW_THINKER_MODEL env var changes the Slow Critic entry."""
    os.environ["SLOW_THINKER_MODEL"] = "qwen2.5:8b-instruct"
    response = client.get("/api/system/models")
    assert response.status_code == 200
    models = response.json()["models"]
    slow = models[1]
    # Should now reflect 8B instead of 14B for the slow slot
    assert "8.0B" in slow["parameters"] or "8B" in slow["name"]


def test_system_models_dynamic_vision_model():
    """Setting VISION_MODEL env var changes the Vision OCR entry."""
    os.environ["VISION_MODEL"] = "moondream:latest"
    response = client.get("/api/system/models")
    assert response.status_code == 200
    models = response.json()["models"]
    vision = models[2]
    assert "Moondream" in vision["name"]


def test_system_models_dynamic_embedding_model():
    """Setting EMBEDDING_MODEL env var changes the Embedding entry."""
    os.environ["EMBEDDING_MODEL"] = "nomic-embed-text"  # same as default — verifies no crash
    response = client.get("/api/system/models")
    assert response.status_code == 200
    models = response.json()["models"]
    embedding = models[4]
    assert embedding["name"] == "nomic-embed-text"


def test_system_models_unknown_model_id():
    """An unrecognized model ID returns a generic entry with the raw name."""
    os.environ["FAST_THINKER_MODEL"] = "unknown-model:v42"
    response = client.get("/api/system/models")
    assert response.status_code == 200
    models = response.json()["models"]
    fast = models[0]
    assert fast["name"] == "unknown-model:v42"
    assert fast["parameters"] == "Unknown"
    assert fast["license"] == "Unknown"
    assert "model_id" in fast
    assert fast["model_id"] == "unknown-model:v42"


def test_system_models_public_access_no_auth_required():
    """The endpoint must be publicly accessible without authentication."""
    response = client.get("/api/system/models")
    assert response.status_code == 200


def test_system_models_kokoro_tts_unchanged_by_env_vars():
    """The Kokoro TTS entry remains fixed regardless of env var overrides."""
    os.environ["FAST_THINKER_MODEL"] = "qwen2.5:3b-instruct"
    os.environ["SLOW_THINKER_MODEL"] = "qwen2.5:14b-instruct"
    response = client.get("/api/system/models")
    assert response.status_code == 200
    models = response.json()["models"]
    tts = models[3]
    assert tts["component"] == "Local Speech Synthesis (TTS)"
    assert tts["name"] == "Kokoro-82M ONNX"
    assert tts["parameters"] == "82M"