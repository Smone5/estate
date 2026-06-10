"""
Mock LLM Provider Service (T50 — CI/CD Offline Test Wrapper)
==============================================================
Drop-in replacement for `app/services/llm_provider.py` that returns
pre-cached string responses, structured JSON, vision extractions,
and embeddings — zero network, zero model loading, instant execution.

Usage in tests:
    from app.tests.mock_llm import MockLLMProvider
    provider = MockLLMProvider()
    text = provider.generate_text("fast", "system prompt", "user input", 0.5)
"""

from typing import List, Dict, Optional, Type
from pydantic import BaseModel

# ── Pre-cached responses ────────────────────────────────────────────────────

FAST_MEDIATOR_RESPONSE = (
    "I hear how much this piece means to you — it carries a lifetime of "
    "family memories. Take your time reflecting on what feels right."
)

SLOW_CRITIQUE_PASS = '{"violation": false, "reason": ""}'

SLOW_CRITIQUE_FAIL = (
    '{"violation": true, "reason": "Mediator implicitly promised the '
    "grandfather clock to the heir by saying 'you will treasure it'.\"}"
)

ROUTER_CHAT = "CHAT_MEDIATION"
ROUTER_VALUATION = "VALUATION_SUBMISSION"
ROUTER_OVERRIDE = "ADMIN_OVERRIDE"

VISION_OCR_RESULT = (
    "Title: Antique Mahogany Desk\n"
    "Category: Furniture\n"
    "Tags: mahogany, victorian, desk, brass-handles\n"
    "Description: A late-Victorian mahogany writing desk with brass "
    "hardware and green leather inlay. Approx. 4ft wide."
)

EMBEDDING_VECTOR = [0.0123, -0.0456, 0.0789] + [0.0] * 765  # 768-dim dense vector


class MockLLMProvider:
    """
    Offline mock for `app/services/llm_provider.py`.
    Call `set_scenario()` before tests to control response behavior.
    """

    def __init__(self):
        self._scenario = "default"
        self._call_log: List[Dict] = []
        self._health_status = True  # Simulate Ollama health
        self._retry_count = 0

    # ── Scenario control ────────────────────────────────────────────────────

    def set_scenario(self, scenario: str):
        """
        Available scenarios:
          - "default"         Normal responses
          - "critique_fail"   SLOW_CRITIQUE returns violation=true
          - "ollama_down"     Simulate first health-check fail, then recover
          - "timeout"         Simulate httpx.Timeout exception
        """
        self._scenario = scenario
        self._call_log.clear()

    # ── Health-check (T50 consolidated) ─────────────────────────────────────

    def check_ollama_health(self) -> bool:
        if self._scenario == "ollama_down" and self._retry_count == 0:
            self._retry_count += 1
            self._health_status = False
            return False
        self._health_status = True
        return True

    # ── Provider API ────────────────────────────────────────────────────────

    def generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float = 0.5,
        history: Optional[List[Dict]] = None,
    ) -> str:
        self._call_log.append({"method": "generate_text", "model": model_key})
        if self._scenario == "timeout":
            import httpx
            raise httpx.ReadTimeout("Simulated timeout")

        if model_key in ("fast", "FAST_THINKER_MODEL", "qwen2.5:8b-instruct"):
            return FAST_MEDIATOR_RESPONSE
        if model_key in ("slow", "SLOW_THINKER_MODEL", "qwen2.5:14b-instruct"):
            if self._scenario == "critique_fail":
                return SLOW_CRITIQUE_FAIL
            return SLOW_CRITIQUE_PASS
        return FAST_MEDIATOR_RESPONSE

    def generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float = 0.0,
    ) -> BaseModel:
        self._call_log.append({"method": "generate_structured", "model": model_key})
        import json
        if "ROUTER" in system_prompt.upper() or "routing" in system_prompt.lower():
            return response_model(**{"intent": ROUTER_CHAT})
        if self._scenario == "critique_fail":
            return response_model(**{"violation": True, "reason": "Mock violation"})
        return response_model(**{"violation": False, "reason": ""})

    def generate_vision(self, model_key: str, image_bytes: bytes, prompt: str) -> str:
        self._call_log.append({"method": "generate_vision", "model": model_key})
        return VISION_OCR_RESULT

    def get_embeddings(self, model_key: str, text: str) -> List[float]:
        self._call_log.append({"method": "get_embeddings", "model": model_key})
        return EMBEDDING_VECTOR