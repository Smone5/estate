"""
LLM Provider Abstraction Layer (T50)
====================================
Unified factory abstracting all LLM calls behind a single interface, powered by
LiteLLM. Supports: Ollama (default), OpenAI, Anthropic, Google Gemini, OpenRouter,
NVIDIA NIM — and, since every call is routed through `litellm.completion()` /
`litellm.embedding()`, any other LiteLLM-supported provider (Groq, Mistral, Bedrock,
Azure, Together, etc.) by simply pointing a model env var at that provider's
`provider/model` string and setting its API key — no code change required.

Environment-driven configuration — no hard-coded providers.

Includes:
  - Ollama health-check polling with automatic retry/probe logic
  - Langfuse/Langtrace self-hosted tracing observability
  - Structured logging at entry/exit for every call
"""

import io as _io
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Type

import httpx
import litellm
from PIL import Image as _PILImage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Let callers control verbosity via standard logging; don't let litellm spam stdout.
litellm.suppress_debug_info = True
# Not every provider supports every kwarg (e.g. response_format on ollama_chat) —
# drop unsupported ones instead of raising, since generate_structured() always
# embeds the JSON schema directly in the prompt as a provider-agnostic fallback.
litellm.drop_params = True

# ---------------------------------------------------------------------------
# Provider identifiers
# ---------------------------------------------------------------------------
PROVIDER_OLLAMA = "ollama"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GOOGLE = "google"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_NVIDIA = "nvidia"

# ---------------------------------------------------------------------------
# Per-provider LiteLLM routing config: the model-string prefix LiteLLM expects,
# and which env vars hold the API key / base URL for that provider. This table
# is the entire surface area needed to support a provider — there is no longer
# any provider-specific request/response handling code below.
# ---------------------------------------------------------------------------
_PROVIDER_CONFIG: Dict[str, Dict[str, str]] = {
    PROVIDER_OLLAMA: {
        "prefix": "ollama_chat/",
        # Ollama's embedding endpoint isn't exposed under ollama_chat/ — only
        # the plain ollama/ route supports litellm.embedding().
        "embedding_prefix": "ollama/",
        "api_base_env": "OLLAMA_BASE_URL",
    },
    PROVIDER_OPENAI: {
        "prefix": "",
        "api_key_env": "OPENAI_API_KEY",
    },
    PROVIDER_ANTHROPIC: {
        "prefix": "anthropic/",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    PROVIDER_GOOGLE: {
        "prefix": "gemini/",
        "api_key_env": "GEMINI_API_KEY",
    },
    PROVIDER_OPENROUTER: {
        "prefix": "openrouter/",
        "api_key_env": "OPENROUTER_API_KEY",
        "api_base_env": "OPENROUTER_BASE_URL",
    },
    PROVIDER_NVIDIA: {
        "prefix": "nvidia_nim/",
        "api_key_env": "NVIDIA_API_KEY",
        "api_base_env": "NVIDIA_BASE_URL",
    },
}

_VALID_TEXT_PROVIDERS = set(_PROVIDER_CONFIG)
_VALID_EMBEDDING_PROVIDERS = set(_PROVIDER_CONFIG)
_VALID_VISION_PROVIDERS = set(_PROVIDER_CONFIG)

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

# Model profiles (T63 & T07b)
_MODEL_PROFILES = {
    "default": {
        "fast": "qwen2.5:latest",
        "slow": "qwen2.5:14b",
        "vision": "llava:latest",
        "embedding": "nomic-embed-text",
        "fast_token_limit": 150,
        "slow_token_limit": 256,
        "vision_token_limit": 512,
        "timeout_seconds": 60,
        "concurrency_ceiling": 4,
    },
    "pi5": {
        "fast": "qwen2.5:3b-instruct",
        "slow": "qwen2.5:8b-instruct",
        "vision": "moondream:latest",
        "embedding": "nomic-embed-text",
        "fast_token_limit": 100,
        "slow_token_limit": 150,
        "vision_token_limit": 256,
        "timeout_seconds": 30,
        "concurrency_ceiling": 1,
    },
    "pi5_alternative": {
        "fast": "qwen2.5:1.5b-instruct",
        "slow": "qwen2.5:8b-instruct",
        "vision": "llava:7b",
        "embedding": "nomic-embed-text",
        "fast_token_limit": 100,
        "slow_token_limit": 150,
        "vision_token_limit": 256,
        "timeout_seconds": 30,
        "concurrency_ceiling": 1,
    },
}

_MODEL_PROFILE_NAME = os.environ.get("MODEL_PROFILE", "default").strip().lower()
_PROFILE = _MODEL_PROFILES.get(_MODEL_PROFILE_NAME, _MODEL_PROFILES["default"])

_FAST_MODEL = os.environ.get("FAST_THINKER_MODEL", _PROFILE["fast"])
_SLOW_MODEL = os.environ.get("SLOW_THINKER_MODEL", _PROFILE["slow"])
_VISION_MODEL = os.environ.get("VISION_MODEL", _PROFILE["vision"])
_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", _PROFILE["embedding"])

_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

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
# Observability initialisation helpers
# ---------------------------------------------------------------------------

def create_langfuse_handler() -> Optional[Any]:
    """Create a Langfuse CallbackHandler for LangGraph tracing.

    Returns None if Langfuse is not installed or key env vars are missing.
    The caller passes this handler into LangGraph's config.callbacks list.
    """
    if not _LANGFUSE_AVAILABLE:
        return None
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        logger.debug("Langfuse credentials not set — observer disabled")
        return None
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler()
    except Exception as exc:
        logger.warning("Failed to create Langfuse handler: %s", exc)
        return None


def init_langtrace() -> None:
    """Initialise the Langtrace OpenTelemetry SDK.

    Reads LANGTRACE_API_KEY from the environment.  Must be called *before*
    FastAPI app creation (or any LangGraph/Ollama instrumentation) to
    correctly auto-instrument langgraph, ollama, and httpx.
    """
    api_key = os.environ.get("LANGTRACE_API_KEY", "").strip()
    if not api_key:
        return
    if not _LANGTRACE_AVAILABLE:
        logger.warning("langtrace-python-sdk not installed — cannot initialise")
        return
    try:
        from langtrace_python_sdk import langtrace
        langtrace.init(api_key=api_key)
        logger.info("Langtrace OpenTelemetry initialised")
    except Exception as exc:
        logger.warning("Langtrace init failed: %s", exc)


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
    """Unified LLM provider factory, backed by LiteLLM.

    Usage::

        provider = LLMProvider()
        reply = provider.generate_text("fast", system_prompt, user_input, 0.5)
        result = provider.generate_structured("slow", sys, inp, MyModel, 0.0)
        ocr   = provider.generate_vision("vision", image_bytes, "Describe this")
        vec   = provider.get_embeddings("embedding", "query text")

    The provider type and model names are read from environment variables on
    instance creation and are immutable for the lifetime of the process.

    Switching providers (or adding a new one not listed in `_PROVIDER_CONFIG`)
    requires no code change: any LiteLLM-supported model string
    (`"groq/llama-3.1-70b"`, `"mistral/mistral-large-latest"`,
    `"bedrock/anthropic.claude-3-sonnet"`, ...) can be set directly as
    FAST_THINKER_MODEL/SLOW_THINKER_MODEL/VISION_MODEL/EMBEDDING_MODEL —
    LiteLLM reads that provider's own conventional API-key env var.
    """

    def __init__(self):
        # Read env vars at construction time so monkeypatch.setenv works in tests
        self.llm_provider = os.environ.get("LLM_PROVIDER", PROVIDER_OLLAMA).strip().lower()
        self.embedding_provider = os.environ.get("EMBEDDING_PROVIDER", PROVIDER_OLLAMA).strip().lower()
        self.vision_provider = os.environ.get("VISION_PROVIDER", PROVIDER_OLLAMA).strip().lower()

        self._ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

        # Lazy OpenAI SDK client — used only for Whisper audio transcription,
        # which LiteLLM does not abstract for our use case.
        self._openai_client = None

        # Read model profiles & limits (T63 & T07b)
        self.profile_name = os.environ.get("MODEL_PROFILE", "default").strip().lower()
        self.profile = _MODEL_PROFILES.get(self.profile_name, _MODEL_PROFILES["default"])

        self.fast_token_limit = int(os.environ.get("LLM_FAST_TOKEN_LIMIT", self.profile.get("fast_token_limit", 150)))
        self.slow_token_limit = int(os.environ.get("LLM_SLOW_TOKEN_LIMIT", self.profile.get("slow_token_limit", 256)))
        self.vision_token_limit = int(os.environ.get("LLM_VISION_TOKEN_LIMIT", self.profile.get("vision_token_limit", 512)))
        self.timeout_seconds = int(os.environ.get("LLM_TIMEOUT_SECONDS", self.profile.get("timeout_seconds", 60)))
        self.concurrency_ceiling = int(os.environ.get("LLM_CONCURRENCY_CEILING", self.profile.get("concurrency_ceiling", 4)))

        import threading
        self._semaphore = threading.Semaphore(self.concurrency_ceiling)

        # Lazy model-name cache (populated on first _resolve_model call)
        self._cached_fast = None
        self._cached_slow = None
        self._cached_vision = None
        self._cached_embedding = None

        logger.info(
            "LLMProvider initialised: text=%s embedding=%s vision=%s profile=%s concurrency=%d timeout=%d",
            self.llm_provider, self.embedding_provider, self.vision_provider,
            self.profile_name, self.concurrency_ceiling, self.timeout_seconds,
        )

    def get_limits(self, profile_override: Optional[str] = None) -> Dict[str, Any]:
        """Return a dictionary of limits for the active or overridden model profile."""
        p_name = (profile_override or self.profile_name).strip().lower()
        prof = _MODEL_PROFILES.get(p_name, self.profile)
        return {
            "fast_token_limit": prof.get("fast_token_limit", 150),
            "slow_token_limit": prof.get("slow_token_limit", 256),
            "vision_token_limit": prof.get("vision_token_limit", 512),
            "timeout_seconds": prof.get("timeout_seconds", 60),
            "concurrency_ceiling": prof.get("concurrency_ceiling", 4),
        }

    # ------------------------------------------------------------------
    # LiteLLM routing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _provider_kwargs(provider: str) -> Dict[str, Any]:
        """Build the api_key / api_base kwargs LiteLLM needs for this provider."""
        cfg = _PROVIDER_CONFIG.get(provider)
        if cfg is None:
            return {}
        kwargs: Dict[str, Any] = {}
        api_key_env = cfg.get("api_key_env")
        if api_key_env:
            value = os.environ.get(api_key_env, "")
            if value:
                kwargs["api_key"] = value
        api_base_env = cfg.get("api_base_env")
        if api_base_env:
            value = os.environ.get(api_base_env, "")
            if value:
                kwargs["api_base"] = value
        return kwargs

    def _to_litellm_model(self, model_name: str, provider: str, is_embedding: bool = False) -> str:
        """Prefix a bare model name with this provider's LiteLLM prefix.

        If `model_name` already contains a `/`, it's treated as a fully
        qualified LiteLLM route (e.g. a user dropped in
        `FAST_THINKER_MODEL=groq/llama-3.1-70b`) and is passed through
        unchanged.
        """
        if "/" in model_name:
            return model_name
        cfg = _PROVIDER_CONFIG.get(provider)
        if not cfg:
            return model_name
        if is_embedding and "embedding_prefix" in cfg:
            prefix = cfg["embedding_prefix"]
        else:
            prefix = cfg.get("prefix", "")
        return f"{prefix}{model_name}"

    def _completion(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        provider: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        response_format: Optional[Dict[str, str]] = None,
    ):
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            **self._provider_kwargs(provider),
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            kwargs["timeout"] = timeout
        if response_format is not None:
            kwargs["response_format"] = response_format
        try:
            return litellm.completion(**kwargs)
        except Exception as exc:
            logger.error("LiteLLM completion failed for model=%s: %s", model, exc)
            raise

    def _embed(
        self,
        model: str,
        text: str,
        provider: str,
        timeout: Optional[float] = None,
    ) -> List[float]:
        kwargs: Dict[str, Any] = {
            "model": model,
            "input": [text],
            **self._provider_kwargs(provider),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            resp = litellm.embedding(**kwargs)
        except Exception as exc:
            logger.error("LiteLLM embedding failed for model=%s: %s", model, exc)
            raise
        data = resp.data if hasattr(resp, "data") else resp["data"]
        if not data:
            raise ValueError("LiteLLM returned empty embeddings array")
        item = data[0]
        return item["embedding"] if isinstance(item, dict) else item.embedding

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
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Generate a plain-text completion."""
        if self.llm_provider not in _VALID_TEXT_PROVIDERS:
            raise ValueError(f"Unsupported text provider: {self.llm_provider}")

        if max_tokens is None:
            if model_key == MODEL_KEY_FAST:
                max_tokens = self.fast_token_limit
            elif model_key == MODEL_KEY_SLOW:
                max_tokens = self.slow_token_limit
            elif model_key == MODEL_KEY_VISION:
                max_tokens = self.vision_token_limit
        if timeout is None:
            timeout = self.timeout_seconds

        model = self._to_litellm_model(self._resolve_model(model_key), self.llm_provider)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_input})

        logger.debug(
            "[LLMProvider] generate_text model_key=%s model=%s temperature=%.2f prompt_len=%d max_tokens=%s timeout=%s",
            model_key, model, temperature, len(user_input), max_tokens, timeout,
        )
        with self._semaphore:
            resp = self._completion(
                model, messages, self.llm_provider,
                temperature=temperature, max_tokens=max_tokens, timeout=timeout,
            )
        result = resp.choices[0].message.content.strip()
        logger.debug("[LLMProvider] generate_text result_len=%d", len(result))
        return result

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
        """Generate a structured (JSON) output validated against a Pydantic model."""
        if self.llm_provider not in _VALID_TEXT_PROVIDERS:
            raise ValueError(f"Unsupported text provider: {self.llm_provider}")

        if max_tokens is None:
            if model_key == MODEL_KEY_FAST:
                max_tokens = self.fast_token_limit
            elif model_key == MODEL_KEY_SLOW:
                max_tokens = self.slow_token_limit
            elif model_key == MODEL_KEY_VISION:
                max_tokens = self.vision_token_limit
        if timeout is None:
            timeout = self.timeout_seconds

        model = self._to_litellm_model(self._resolve_model(model_key), self.llm_provider)
        schema_str = str(response_model.model_json_schema())
        full_system = (
            f"{system_prompt}\n\n"
            f"Respond ONLY with a valid JSON object matching this schema:\n{schema_str}"
        )
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": user_input},
        ]

        logger.debug(
            "[LLMProvider] generate_structured model_key=%s model=%s response_model=%s max_tokens=%s timeout=%s",
            model_key, model, response_model.__name__, max_tokens, timeout,
        )
        with self._semaphore:
            resp = self._completion(
                model, messages, self.llm_provider,
                temperature=temperature, max_tokens=max_tokens, timeout=timeout,
                response_format={"type": "json_object"},
            )
        content = resp.choices[0].message.content.strip()
        parsed = json.loads(content)
        result = response_model(**parsed)
        logger.debug("[LLMProvider] generate_structured OK")
        return result

    def generate_vision(
        self,
        model_key: str,
        image_bytes: bytes,
        prompt: str,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        images: Optional[List[bytes]] = None,
    ) -> str:
        """Vision / OCR extraction from image bytes.

        Args:
            image_bytes: Primary image bytes (required).
            images: Optional list of additional image bytes for multi-image models.
        """
        if self.vision_provider not in _VALID_VISION_PROVIDERS:
            raise ValueError(f"Unsupported vision provider: {self.vision_provider}")

        if max_tokens is None:
            max_tokens = self.vision_token_limit
        if timeout is None:
            timeout = self.timeout_seconds

        model = self._to_litellm_model(self._resolve_model(model_key), self.vision_provider)

        import base64
        all_images = [self._ensure_image_jpeg(image_bytes)] + [
            self._ensure_image_jpeg(img) for img in (images or [])
        ]
        content_list: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in all_images:
            b64 = base64.b64encode(img).decode("utf-8")
            # litellm's ollama_chat transformation forwards image_url.url verbatim
            # into Ollama's native `images` field, which expects bare base64 (no
            # data-URI prefix) — other providers expect the full data: URI.
            url = b64 if self.vision_provider == PROVIDER_OLLAMA else f"data:image/jpeg;base64,{b64}"
            content_list.append({"type": "image_url", "image_url": {"url": url}})
        messages = [{"role": "user", "content": content_list}]

        total_imgs = len(all_images)
        logger.debug(
            "[LLMProvider] generate_vision model_key=%s model=%s imgs=%d prompt_len=%d max_tokens=%s timeout=%s",
            model_key, model, total_imgs, len(prompt), max_tokens, timeout,
        )
        with self._semaphore:
            resp = self._completion(
                model, messages, self.vision_provider,
                temperature=0.0, max_tokens=max_tokens, timeout=timeout,
            )
        result = resp.choices[0].message.content.strip()

        # Strip Gemma-style thinking tokens if present:
        #   <|channel>thought\n...<channel|>
        import re
        result = re.sub(r"<\|channel>thought.*?(?:<channel\|>|$)", "", result, flags=re.DOTALL).strip()

        logger.debug("[LLMProvider] generate_vision result_len=%d", len(result))
        return result

    def get_embeddings(
        self,
        model_key: str,
        text: str,
        timeout: Optional[float] = None,
    ) -> List[float]:
        """Return a dense embedding vector for the given text."""
        if self.embedding_provider not in _VALID_EMBEDDING_PROVIDERS:
            raise ValueError(f"Unsupported embedding provider: {self.embedding_provider}")

        if timeout is None:
            timeout = self.timeout_seconds

        model = self._to_litellm_model(
            self._resolve_model(model_key), self.embedding_provider, is_embedding=True
        )

        logger.debug(
            "[LLMProvider] get_embeddings model_key=%s model=%s text_len=%d timeout=%s",
            model_key, model, len(text), timeout,
        )
        with self._semaphore:
            result = self._embed(model, text, self.embedding_provider, timeout=timeout)
        logger.debug("[LLMProvider] get_embeddings dim=%d", len(result))
        return result

    # ------------------------------------------------------------------
    # model name resolution (lazy per-instance cache — reads env on first access)
    # ------------------------------------------------------------------

    def _resolve_model(self, model_key: str) -> str:
        if model_key == MODEL_KEY_FAST:
            if self._cached_fast is None:
                self._cached_fast = os.environ.get("FAST_THINKER_MODEL", _FAST_MODEL)
            return self._cached_fast
        elif model_key == MODEL_KEY_SLOW:
            if self._cached_slow is None:
                self._cached_slow = os.environ.get("SLOW_THINKER_MODEL", _SLOW_MODEL)
            return self._cached_slow
        elif model_key == MODEL_KEY_VISION:
            if self._cached_vision is None:
                self._cached_vision = os.environ.get("VISION_MODEL", _VISION_MODEL)
            return self._cached_vision
        elif model_key == MODEL_KEY_EMBEDDING:
            if self._cached_embedding is None:
                self._cached_embedding = os.environ.get("EMBEDDING_MODEL", _EMBEDDING_MODEL)
            return self._cached_embedding
        return model_key

    # ------------------------------------------------------------------
    # Image helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_image_jpeg(image_bytes: bytes) -> bytes:
        """Convert image bytes to JPEG if they are in an incompatible format.

        Many vision models cannot decode WebP or HEIC images.  This helper
        detects when the bytestream is not JPEG and re-encodes it via PIL so
        the vision model always receives a format it can handle.
        """
        # Quick magic-byte check: JPEG starts with FF D8 FF
        if image_bytes[:3] == b'\xff\xd8\xff':
            return image_bytes  # already JPEG — no-op
        try:
            img = _PILImage.open(_io.BytesIO(image_bytes))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=92)
            return buf.getvalue()
        except Exception:
            # If PIL can't open it, return as-is and let the model try
            return image_bytes

    # ------------------------------------------------------------------
    # OpenAI SDK client — used only for Whisper audio transcription, which
    # falls outside LiteLLM's completion/embedding abstraction here.
    # ------------------------------------------------------------------

    def _get_openai_client(self):
        if self._openai_client is None:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=_OPENAI_API_KEY)
            except ImportError:
                raise RuntimeError("openai package required for Whisper transcription")
        return self._openai_client


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
