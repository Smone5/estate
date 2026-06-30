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

from typing import List, Dict, Optional, Type, Any
from pydantic import BaseModel

# ── Pre-cached responses ────────────────------------------------------------

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
          - "reflect_fail"    SLOW_REFLECT returns aligned=false
          - "ollama_down"     Simulate first health-check fail, then recover
          - "timeout"         Simulate httpx.Timeout exception
        """
        self._scenario = scenario
        self._call_log.clear()

    # ── Limits & profiles ───────────────────────────────────────────────────

    def get_limits(self, profile_override: Optional[str] = None) -> Dict[str, Any]:
        """Mock limits matching model profiles."""
        p_name = (profile_override or "default").strip().lower()
        if p_name in ("pi5", "pi5_alternative"):
            return {
                "fast_token_limit": 100,
                "slow_token_limit": 150,
                "vision_token_limit": 256,
                "timeout_seconds": 30,
                "concurrency_ceiling": 1,
            }
        return {
            "fast_token_limit": 150,
            "slow_token_limit": 256,
            "vision_token_limit": 512,
            "timeout_seconds": 60,
            "concurrency_ceiling": 4,
        }

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
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        self._call_log.append({
            "method": "generate_text",
            "model": model_key,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })
        if self._scenario == "timeout":
            import httpx
            raise httpx.ReadTimeout("Simulated timeout")

        if model_key in ("fast", "FAST_THINKER_MODEL", "qwen3:8b"):
            return FAST_MEDIATOR_RESPONSE
        if model_key in ("slow", "SLOW_THINKER_MODEL", "qwen3:14b"):
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
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> BaseModel:
        self._call_log.append({
            "method": "generate_structured",
            "model": model_key,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })
        import json

        # Detect ReflectResult calls
        if response_model.__name__ == "ReflectResult":
            if self._scenario == "reflect_fail":
                return response_model(**{"aligned": False, "reason": "Discrepancy detected: heir likes asset but points assigned is 0"})
            return response_model(**{"aligned": True, "reason": "Valuations aligned with expressed sentiments"})

        # Detect router calls: the prompt always contains "routing" / "ROUTER"
        is_router = (
            "ROUTER" in system_prompt.upper()
            or "routing" in system_prompt.lower()
            or "ROUTER" in user_input.upper()
            or "routing" in user_input.lower()
        )

        if is_router:
            # Extract the actual user text from the formatted prompt to avoid
            # matching keywords inside the prompt template itself
            actual_text = user_input
            if "User Input:" in user_input:
                segment = user_input.split("User Input:")[-1]
                if "\nClass:" in segment:
                    segment = segment.split("\nClass:")[0]
                elif "Class:" in segment:
                    segment = segment.split("Class:")[0]
                actual_text = segment.strip()

            lower = actual_text.lower()
            if "submit" in lower or "allocation" in lower:
                return response_model(**{"intent": ROUTER_VALUATION})
            elif "admin" in lower or "override" in lower:
                return response_model(**{"intent": ROUTER_OVERRIDE})
            return response_model(**{"intent": ROUTER_CHAT})

        # Critique node calls
        if self._scenario == "critique_fail":
            return response_model(**{"violation": True, "reason": "Mock violation"})
        return response_model(**{"violation": False, "reason": ""})

    def generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        self._call_log.append({
            "method": "generate_vision",
            "model": model_key,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })
        return VISION_OCR_RESULT

    def get_embeddings(
        self,
        model_key: str,
        text: str,
        timeout: Optional[float] = None,
    ) -> List[float]:
        self._call_log.append({
            "method": "get_embeddings",
            "model": model_key,
            "timeout": timeout,
        })
        return EMBEDDING_VECTOR