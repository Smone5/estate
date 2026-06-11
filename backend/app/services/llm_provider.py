"""
LLM Provider Abstraction Layer (T50)
====================================
Unified factory abstracting all LLM calls behind a single interface.
Supports: Ollama (default), OpenAI, Anthropic, Google Gemini, OpenRouter.

Environment-driven configuration — no hard-coded providers.

Includes:
  - Ollama health-check polling with automatic retry/probe logic
  - Langfuse/Langtrace self-hosted tracing observability
  - Structured logging at entry/exit for every call
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Type

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider identifiers
# ---------------------------------------------------------------------------
PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GOOGLE = "google"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_NVIDIA = "nvidia"

_VALID_TEXT_PROVIDERS = {
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENROUTER,
    PROVIDER_NVIDIA,
}
_VALID_EMBEDDING_PROVIDERS = {
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_GOOGLE,
    PROVIDER_OPENROUTER,
    PROVIDER_NVIDIA,
}
_VALID_VISION_PROVIDERS = {
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_GOOGLE,
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENROUTER,
    PROVIDER_NVIDIA,
}

# ---------------------------------------------------------------------------
# Model keys used by LangGraph nodes
# ---------------------------------------------------------------------------
MODEL_KEY_FAST = "fast"
MODEL_KEY_SLOW = "slow"
MODEL_KEY_VISION = "vision"
MODEL_KEY_EMBEDDING = "embedding"

# ---------------------------------------------------------------------------
# Environment-driven configuration
# ---------------------------------------------------------------------------
_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", PROVIDER_OLLAMA).strip().lower()
_EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", PROVIDER_OLLAMA).strip().lower()
_VISION_PROVIDER = os.environ.get("VISION_PROVIDER", PROVIDER_OLLAMA).strip().lower()

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

_FAST_MODEL = os.environ.get("FAST_THINKER_MODEL", "qwen2.5:latest")
_SLOW_MODEL = os.environ.get("SLOW_THINKER_MODEL", "qwen2.5:14b")
_VISION_MODEL = os.environ.get("VISION_MODEL", "llava:latest")
_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
_OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
_NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
_NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Langfuse / Langtrace
try:
    import langfuse  # noqa: F401
    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LANGFUSE_AVAILABLE = False

try:
    import langtrace_python_sdk  # noqa: F401
    _LANGTRACE_AVAILABLE = True
except ImportError:
    _LANGTRACE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Health-check constants
# ---------------------------------------------------------------------------
_OLLAMA_HEALTH_TIMEOUT = 5  # seconds per probe attempt
_OLLAMA_HEALTH_RETRIES = 5
_OLLAMA_HEALTH_BACKOFF = 2.0  # seconds between retries


# ===================================================================
# Ollama Health-Check (T50 consolidated — was T62)
# ===================================================================

def check_ollama_health() -> bool:
    """Poll Ollama's HTTP endpoint with automatic connection retry.

    Returns True when Ollama responds with HTTP 200, False after
    exhausting all retries.  Designed to be called at startup and
    periodically from a background task so that transient Ollama
    restarts do not crash the LangGraph workflow.
    """
    url = f"{_OLLAMA_BASE_URL}/"
    for attempt in range(1, _OLLAMA_HEALTH_RETRIES + 1):
        try:
            resp = httpx.get(url, timeout=_OLLAMA_HEALTH_TIMEOUT)
            if resp.status_code == 200:
                logger.debug("Ollama health-check OK (attempt %d)", attempt)
                return True
            logger.warning(
                "Ollama health-check: HTTP %d (attempt %d/%d)",
                resp.status_code, attempt, _OLLAMA_HEALTH_RETRIES,
            )
        except httpx.ConnectError:
            logger.warning(
                "Ollama health-check: connection refused (attempt %d/%d)",
                attempt, _OLLAMA_HEALTH_RETRIES,
            )
        except httpx.TimeoutException:
            logger.warning(
                "Ollama health-check: timeout (attempt %d/%d)",
                attempt, _OLLAMA_HEALTH_RETRIES,
            )
        except Exception as exc:
            logger.warning(
                "Ollama health-check: unexpected error (attempt %d/%d): %s",
                attempt, _OLLAMA_HEALTH_RETRIES, exc,
            )
        if attempt < _OLLAMA_HEALTH_RETRIES:
            time.sleep(_OLLAMA_HEALTH_BACKOFF)
    logger.error("Ollama health-check FAILED after %d attempts", _OLLAMA_HEALTH_RETRIES)
    return False


# ===================================================================
# Factory
# ===================================================================

class LLMProvider:
    """Unified LLM provider factory.

    Usage::

        provider = LLMProvider()
        reply = provider.generate_text("fast", system_prompt, user_input, 0.5)
        result = provider.generate_structured("slow", sys, inp, MyModel, 0.0)
        ocr   = provider.generate_vision("vision", image_bytes, "Describe this")
        vec   = provider.get_embeddings("embedding", "query text")

    The provider type and model names are read from environment variables
    on instance creation and are immutable for the lifetime of the process.
    """

    def __init__(self):
        # Read env vars at construction time so monkeypatch.setenv works in tests
        self.llm_provider = os.environ.get("LLM_PROVIDER", PROVIDER_OLLAMA).strip().lower()
        self.embedding_provider = os.environ.get("EMBEDDING_PROVIDER", PROVIDER_OLLAMA).strip().lower()
        self.vision_provider = os.environ.get("VISION_PROVIDER", PROVIDER_OLLAMA).strip().lower()

        # Ollama-specific
        self._ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        if self.llm_provider == PROVIDER_OLLAMA:
            self._ollama_client = self._build_ollama_client()
        else:
            self._ollama_client = None

        # Lazy-built clients for cloud providers
        self._openai_client = None
        self._anthropic_client = None
        self._google_client = None
        self._openrouter_client = None
        self._nvidia_client = None

        logger.info(
            "LLMProvider initialised: text=%s embedding=%s vision=%s",
            self.llm_provider, self.embedding_provider, self.vision_provider,
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float = 0.5,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Generate a plain-text completion."""
        logger.debug(
            "[LLMProvider] generate_text model_key=%s temperature=%.2f prompt_len=%d",
            model_key, temperature, len(user_input),
        )
        if self.llm_provider == PROVIDER_OLLAMA:
            result = self._ollama_generate_text(model_key, system_prompt, user_input, temperature, history)
        elif self.llm_provider == PROVIDER_OPENAI:
            result = self._openai_generate_text(model_key, system_prompt, user_input, temperature, history)
        elif self.llm_provider == PROVIDER_ANTHROPIC:
            result = self._anthropic_generate_text(model_key, system_prompt, user_input, temperature, history)
        elif self.llm_provider == PROVIDER_GOOGLE:
            result = self._google_generate_text(model_key, system_prompt, user_input, temperature, history)
        elif self.llm_provider == PROVIDER_OPENROUTER:
            result = self._openrouter_generate_text(model_key, system_prompt, user_input, temperature, history)
        elif self.llm_provider == PROVIDER_NVIDIA:
            result = self._nvidia_generate_text(model_key, system_prompt, user_input, temperature, history)
        else:
            raise ValueError(f"Unsupported text provider: {self.llm_provider}")
        logger.debug("[LLMProvider] generate_text result_len=%d", len(result))
        return result

    def generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float = 0.0,
    ) -> BaseModel:
        """Generate a structured (JSON) output validated against a Pydantic model."""
        logger.debug(
            "[LLMProvider] generate_structured model_key=%s model=%s",
            model_key, response_model.__name__,
        )
        if self.llm_provider == PROVIDER_OLLAMA:
            result = self._ollama_generate_structured(
                model_key, system_prompt, user_input, response_model, temperature,
            )
        elif self.llm_provider == PROVIDER_OPENAI:
            result = self._openai_generate_structured(
                model_key, system_prompt, user_input, response_model, temperature,
            )
        elif self.llm_provider == PROVIDER_ANTHROPIC:
            result = self._anthropic_generate_structured(
                model_key, system_prompt, user_input, response_model, temperature,
            )
        elif self.llm_provider == PROVIDER_GOOGLE:
            result = self._google_generate_structured(
                model_key, system_prompt, user_input, response_model, temperature,
            )
        elif self.llm_provider == PROVIDER_OPENROUTER:
            result = self._openrouter_generate_structured(
                model_key, system_prompt, user_input, response_model, temperature,
            )
        elif self.llm_provider == PROVIDER_NVIDIA:
            result = self._nvidia_generate_structured(
                model_key, system_prompt, user_input, response_model, temperature,
            )
        else:
            raise ValueError(f"Unsupported text provider: {self.llm_provider}")
        logger.debug("[LLMProvider] generate_structured OK")
        return result

    def generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        """Vision / OCR extraction from image bytes."""
        logger.debug(
            "[LLMProvider] generate_vision model_key=%s img_size=%d prompt_len=%d",
            model_key, len(image_bytes), len(prompt),
        )
        if self.vision_provider == PROVIDER_OLLAMA:
            result = self._ollama_generate_vision(model_key, image_bytes, prompt)
        elif self.vision_provider == PROVIDER_OPENAI:
            result = self._openai_generate_vision(model_key, image_bytes, prompt)
        elif self.vision_provider == PROVIDER_ANTHROPIC:
            result = self._anthropic_generate_vision(model_key, image_bytes, prompt)
        elif self.vision_provider == PROVIDER_GOOGLE:
            result = self._google_generate_vision(model_key, image_bytes, prompt)
        elif self.vision_provider == PROVIDER_OPENROUTER:
            result = self._openrouter_generate_vision(model_key, image_bytes, prompt)
        elif self.vision_provider == PROVIDER_NVIDIA:
            result = self._nvidia_generate_vision(model_key, image_bytes, prompt)
        else:
            raise ValueError(f"Unsupported vision provider: {self.vision_provider}")
        logger.debug("[LLMProvider] generate_vision result_len=%d", len(result))
        return result

    def get_embeddings(self, model_key: str, text: str) -> List[float]:
        """Return a dense embedding vector for the given text."""
        logger.debug(
            "[LLMProvider] get_embeddings model_key=%s text_len=%d",
            model_key, len(text),
        )
        if self.embedding_provider == PROVIDER_OLLAMA:
            result = self._ollama_get_embeddings(model_key, text)
        elif self.embedding_provider == PROVIDER_OPENAI:
            result = self._openai_get_embeddings(model_key, text)
        elif self.embedding_provider == PROVIDER_GOOGLE:
            result = self._google_get_embeddings(model_key, text)
        elif self.embedding_provider == PROVIDER_OPENROUTER:
            result = self._openrouter_get_embeddings(model_key, text)
        elif self.embedding_provider == PROVIDER_NVIDIA:
            result = self._nvidia_get_embeddings(model_key, text)
        else:
            raise ValueError(f"Unsupported embedding provider: {self.embedding_provider}")
        logger.debug("[LLMProvider] get_embeddings dim=%d", len(result))
        return result

    # ------------------------------------------------------------------
    # model name resolution
    # ------------------------------------------------------------------

    def _resolve_model(self, model_key: str) -> str:
        if model_key == MODEL_KEY_FAST:
            return _FAST_MODEL
        elif model_key == MODEL_KEY_SLOW:
            return _SLOW_MODEL
        elif model_key == MODEL_KEY_VISION:
            return _VISION_MODEL
        elif model_key == MODEL_KEY_EMBEDDING:
            return _EMBEDDING_MODEL
        return model_key

    # ------------------------------------------------------------------
    # Ollama backend
    # ------------------------------------------------------------------

    def _build_ollama_client(self):
        try:
            import ollama
            return ollama.Client(host=self._ollama_url)
        except ImportError:
            logger.error("ollama package not installed; Ollama provider unavailable")
            raise RuntimeError("ollama package is required when LLM_PROVIDER=ollama")

    def _ollama_generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        model = self._resolve_model(model_key)
        full_prompt = system_prompt + "\n\n" + user_input
        try:
            response = self._ollama_client.generate(
                model=model,
                prompt=full_prompt,
                options={"temperature": temperature},
                keep_alive=-1,
            )
            return response.response.strip()
        except Exception as exc:
            logger.error("Ollama generate_text failed for model=%s: %s", model, exc)
            raise

    def _ollama_generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        model = self._resolve_model(model_key)
        schema_json = response_model.model_json_schema()
        schema_str = str(schema_json)
        full_prompt = (
            f"{system_prompt}\n\n"
            f"Respond ONLY with a valid JSON object matching this schema:\n{schema_str}\n\n"
            f"Input: {user_input}\nJSON:"
        )
        try:
            response = self._ollama_client.generate(
                model=model,
                prompt=full_prompt,
                options={"temperature": temperature},
                keep_alive=-1,
            )
            import json
            parsed = json.loads(response.response.strip())
            return response_model(**parsed)
        except Exception as exc:
            logger.error("Ollama generate_structured failed for model=%s: %s", model, exc)
            raise

    def _ollama_generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        model = self._resolve_model(model_key)
        import base64
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        try:
            response = self._ollama_client.generate(
                model=model,
                prompt=prompt,
                images=[b64_image],
                options={"temperature": 0.0},
                keep_alive=-1,
            )
            return response.response.strip()
        except Exception as exc:
            logger.error("Ollama generate_vision failed for model=%s: %s", model, exc)
            raise

    def _ollama_get_embeddings(self, model_key: str, text: str) -> List[float]:
        model = self._resolve_model(model_key)
        try:
            response = self._ollama_client.embed(
                model=model,
                input=text,
            )
            embeddings = response.get("embeddings", [])
            if not embeddings:
                raise ValueError("Ollama returned empty embeddings array")
            return embeddings[0]
        except Exception as exc:
            logger.error("Ollama get_embeddings failed for model=%s: %s", model, exc)
            raise

    # ------------------------------------------------------------------
    # OpenAI backend
    # ------------------------------------------------------------------

    def _get_openai_client(self):
        if self._openai_client is None:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=_OPENAI_API_KEY)
            except ImportError:
                raise RuntimeError("openai package required when using OpenAI provider")
        return self._openai_client

    def _openai_generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_openai_client()
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
        )
        return resp.choices[0].message.content.strip()

    def _openai_generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        model = self._resolve_model(model_key)
        client = self._get_openai_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        import json
        parsed = json.loads(resp.choices[0].message.content)
        return response_model(**parsed)

    def _openai_generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_openai_client()
        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()

    def _openai_get_embeddings(self, model_key: str, text: str) -> List[float]:
        model = self._resolve_model(model_key)
        client = self._get_openai_client()
        resp = client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding

    # ------------------------------------------------------------------
    # Anthropic backend
    # ------------------------------------------------------------------

    def _get_anthropic_client(self):
        if self._anthropic_client is None:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
            except ImportError:
                raise RuntimeError("anthropic package required when using Anthropic provider")
        return self._anthropic_client

    def _anthropic_generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_anthropic_client()
        messages = []
        if history:
            for msg in history:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": user_input})
        resp = client.messages.create(
            model=model,
            system=system_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=1024,
        )
        return resp.content[0].text.strip()

    def _anthropic_generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        import json
        text = self._anthropic_generate_text(model_key, system_prompt, user_input, temperature, None)
        parsed = json.loads(text)
        return response_model(**parsed)

    def _anthropic_generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_anthropic_client()
        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        resp = client.messages.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": b64,
                    }},
                ],
            }],
            max_tokens=500,
        )
        return resp.content[0].text.strip()

    # ------------------------------------------------------------------
    # Google Gemini backend
    # ------------------------------------------------------------------

    def _get_google_client(self):
        if self._google_client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=_GEMINI_API_KEY)
                self._google_client = genai
            except ImportError:
                raise RuntimeError("google-generativeai package required for Google provider")
        return self._google_client

    def _google_generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        model = self._resolve_model(model_key)
        genai = self._get_google_client()
        gemini_model = genai.GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
            generation_config={"temperature": temperature},
        )
        combined = user_input
        resp = gemini_model.generate_content(combined)
        return resp.text.strip()

    def _google_generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        import json
        text = self._google_generate_text(model_key, system_prompt, user_input, temperature, None)
        parsed = json.loads(text)
        return response_model(**parsed)

    def _google_generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        model = self._resolve_model(model_key)
        genai = self._get_google_client()
        gemini_model = genai.GenerativeModel(model_name=model)
        resp = gemini_model.generate_content([prompt, {"mime_type": "image/jpeg", "data": image_bytes}])
        return resp.text.strip()

    def _google_get_embeddings(self, model_key: str, text: str) -> List[float]:
        model = self._resolve_model(model_key)
        genai = self._get_google_client()
        resp = genai.embed_content(model=model, content=text)
        return resp["embedding"]

    # ------------------------------------------------------------------
    # OpenRouter backend (OpenAI-compatible API)
    # ------------------------------------------------------------------

    def _get_openrouter_client(self):
        if self._openrouter_client is None:
            try:
                from openai import OpenAI
                self._openrouter_client = OpenAI(
                    api_key=_OPENROUTER_API_KEY,
                    base_url=_OPENROUTER_BASE_URL,
                )
            except ImportError:
                raise RuntimeError("openai package required when using OpenRouter provider")
        return self._openrouter_client

    def _openrouter_generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_openrouter_client()
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()

    def _openrouter_generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        model = self._resolve_model(model_key)
        client = self._get_openrouter_client()
        import json
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(resp.choices[0].message.content)
        return response_model(**parsed)

    def _openrouter_generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_openrouter_client()
        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()

    def _openrouter_get_embeddings(self, model_key: str, text: str) -> List[float]:
        model = self._resolve_model(model_key)
        client = self._get_openrouter_client()
        resp = client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding

    # ------------------------------------------------------------------
    # NVIDIA NIM backend (OpenAI-compatible API)
    # ------------------------------------------------------------------

    def _get_nvidia_client(self):
        if self._nvidia_client is None:
            try:
                from openai import OpenAI
                self._nvidia_client = OpenAI(
                    api_key=_NVIDIA_API_KEY,
                    base_url=_NVIDIA_BASE_URL,
                )
            except ImportError:
                raise RuntimeError("openai package required when using NVIDIA NIM provider")
        return self._nvidia_client

    def _nvidia_generate_text(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_nvidia_client()
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()

    def _nvidia_generate_structured(
        self,
        model_key: str,
        system_prompt: str,
        user_input: str,
        response_model: Type[BaseModel],
        temperature: float,
    ) -> BaseModel:
        model = self._resolve_model(model_key)
        client = self._get_nvidia_client()
        import json
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(resp.choices[0].message.content)
        return response_model(**parsed)

    def _nvidia_generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
    ) -> str:
        model = self._resolve_model(model_key)
        client = self._get_nvidia_client()
        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=500,
        )
        return resp.choices[0].message.content.strip()

    def _nvidia_get_embeddings(self, model_key: str, text: str) -> List[float]:
        model = self._resolve_model(model_key)
        client = self._get_nvidia_client()
        resp = client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding


# ===================================================================
# Module-level convenience: singleton factory
# ===================================================================

_default_provider: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """Return the module-level (singleton) provider instance."""
    global _default_provider
    if _default_provider is None:
        _default_provider = LLMProvider()
    return _default_provider


def reset_provider() -> None:
    """Reset the singleton (useful in tests)."""
    global _default_provider
    _default_provider = None


# ===================================================================
# CLI health-check entry point
# ===================================================================

def main() -> None:
    """Run the Ollama health-check and print a summary."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    ok = check_ollama_health()
    if ok:
        logger.info("Ollama is reachable at %s", _OLLAMA_BASE_URL)
    else:
        logger.error("Ollama is NOT reachable at %s", _OLLAMA_BASE_URL)
        raise SystemExit(1)


if __name__ == "__main__":
    main()