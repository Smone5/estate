"""
Ollama model reachability and basic inference verification (T06b).

Verifies that the four required Ollama models are installed and
return valid responses within expected timeouts.  Used as a
startup health check and for ad-hoc verification.

Does NOT gate application startup — failures emit WARNING logs.
"""

import logging
import os

import ollama

logger = logging.getLogger(__name__)

# ---- configurable model names (defaults from .env.example) ----------
_FAST_MODEL = os.environ.get("FAST_THINKER_MODEL", "qwen3:8b")
_SLOW_MODEL = os.environ.get("SLOW_THINKER_MODEL", "qwen3:14b")
_VISION_MODEL = os.environ.get("VISION_MODEL", "qwen3-vl:8b")
_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
_INFERENCE_TIMEOUT_S = 120  # generous — first-pull warm-up can be slow


def _client() -> ollama.Client:
    return ollama.Client(host=_OLLAMA_BASE_URL)


def verify_all_models() -> dict[str, bool]:
    """Run a quick smoke test on every required model.

    Returns a dict mapping model name → True (accessible) / False (failed).
    """
    client = _client()
    results: dict[str, bool] = {}

    # 1 — installed-models cross-check (handle :latest suffix normalisation)
    try:
        raw_names = {m.model for m in client.list().models}
    except Exception as exc:
        logger.warning("Ollama not reachable at %s: %s", _OLLAMA_BASE_URL, exc)
        return {
            _FAST_MODEL: False,
            _SLOW_MODEL: False,
            _VISION_MODEL: False,
            _EMBEDDING_MODEL: False,
        }

    def _installed(tag: str) -> bool:
        """Return True if *tag* matches any installed model.
        Strips ':latest' from both sides before comparison to normalise
        Ollama's inconsistent tagging behaviour.
        """
        normalised = tag.removesuffix(":latest")
        for installed_name in raw_names:
            if installed_name.removesuffix(":latest") == normalised:
                return True
        return False

    for name in (_FAST_MODEL, _SLOW_MODEL, _VISION_MODEL, _EMBEDDING_MODEL):
        if not _installed(name):
            logger.warning("Model '%s' is not installed in Ollama", name)
            results[name] = False

    # 2 — text inference on chat models
    test_prompt = "Respond with exactly one word: OK"

    for model in (_FAST_MODEL, _SLOW_MODEL, _VISION_MODEL):
        try:
            response = client.generate(
                model=model,
                prompt=test_prompt,
                options={"temperature": 0.0},
                keep_alive=-1,
            )
            # A valid response is any non-empty string
            ok = bool(response.response.strip())
            results[model] = ok
            if ok:
                logger.info("Model '%s' inference OK (len=%d)", model, len(response.response))
            else:
                logger.warning("Model '%s' returned empty response", model)
        except Exception as exc:
            logger.warning("Model '%s' inference failed: %s", model, exc)
            results[model] = False

    # 3 — embedding inference
    try:
        embeddings = client.embed(
            model=_EMBEDDING_MODEL,
            input="test vector query",
        )
        # nomic-embed-text produces 768-dim vectors
        ok = (
            "embeddings" in embeddings
            and len(embeddings["embeddings"]) > 0
            and len(embeddings["embeddings"][0]) == 768
        )
        results[_EMBEDDING_MODEL] = ok
        if ok:
            logger.info(
                "Embedding model '%s' OK (dim=%d)",
                _EMBEDDING_MODEL,
                len(embeddings["embeddings"][0]),
            )
        else:
            logger.warning("Embedding model '%s' returned unexpected shape", _EMBEDDING_MODEL)
    except Exception as exc:
        logger.warning("Embedding model '%s' failed: %s", _EMBEDDING_MODEL, exc)
        results[_EMBEDDING_MODEL] = False

    return results


# ---- CLI entry point for ad-hoc verification ------------------------


def main() -> None:
    """Run verify_all_models and print a summary to stdout."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    results = verify_all_models()
    all_ok = all(results.values())
    print()
    for model, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {model}")
    print(f"\nOverall: {'ALL OK' if all_ok else 'SOME MODELS FAILED'}")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()