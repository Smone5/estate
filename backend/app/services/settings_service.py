"""
Admin-editable runtime settings (LLM, SMTP, storage).

Backs the Admin Dashboard "Settings" panel. A static allowlist
(SETTINGS_REGISTRY) is the security boundary — only keys listed here can ever
be read or written through the admin API, so infra-level secrets like
JWT_SECRET, ENCRYPTION_KEY, or DB_URL can never be touched this way.

Values are persisted to the app_settings table (one row per key, encrypted at
rest via EncryptedJSON) and mirrored into os.environ so every service that
reads its config from the environment (llm_provider, smtp_service, storage)
picks up changes immediately, without a restart.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import AppSetting
from . import llm_provider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry: the only keys that can be read/written via the admin settings API.
# ---------------------------------------------------------------------------

_PROVIDER_CHOICES = ["ollama", "openai", "anthropic", "google", "openrouter", "nvidia"]

SETTINGS_REGISTRY: Dict[str, Dict[str, Any]] = {
    # --- LLM ---
    # Each purpose (fast, slow, vision, embedding, pricing) has its own independent
    # provider so admins can mix freely — e.g. local Ollama for fast, Anthropic for
    # slow, Google for vision, OpenAI for pricing.
    # LLM_PROVIDER is the legacy fallback: if FAST_PROVIDER / SLOW_PROVIDER are left
    # blank, both fall back to LLM_PROVIDER, so existing installs keep working.
    "LLM_PROVIDER": {"section": "llm", "secret": False, "choices": _PROVIDER_CHOICES},
    "FAST_PROVIDER": {"section": "llm", "secret": False, "choices": _PROVIDER_CHOICES},
    "SLOW_PROVIDER": {"section": "llm", "secret": False, "choices": _PROVIDER_CHOICES},
    "VISION_PROVIDER": {"section": "llm", "secret": False, "choices": _PROVIDER_CHOICES},
    "EMBEDDING_PROVIDER": {"section": "llm", "secret": False, "choices": _PROVIDER_CHOICES},
    "PRICING_PROVIDER": {"section": "llm", "secret": False, "choices": _PROVIDER_CHOICES},
    "FAST_THINKER_MODEL": {"section": "llm", "secret": False},
    "FAST_API_KEY": {"section": "llm", "secret": True},
    "FAST_BASE_URL": {"section": "llm", "secret": False},
    "SLOW_THINKER_MODEL": {"section": "llm", "secret": False},
    "SLOW_API_KEY": {"section": "llm", "secret": True},
    "SLOW_BASE_URL": {"section": "llm", "secret": False},
    "VISION_MODEL": {"section": "llm", "secret": False},
    "VISION_API_KEY": {"section": "llm", "secret": True},
    "VISION_BASE_URL": {"section": "llm", "secret": False},
    "EMBEDDING_MODEL": {"section": "llm", "secret": False},
    "EMBEDDING_API_KEY": {"section": "llm", "secret": True},
    "EMBEDDING_BASE_URL": {"section": "llm", "secret": False},
    "PRICING_MODEL": {"section": "llm", "secret": False},
    "PRICING_API_KEY": {"section": "llm", "secret": True},
    "PRICING_BASE_URL": {"section": "llm", "secret": False},
    "OLLAMA_BASE_URL": {"section": "llm", "secret": False},
    "OPENAI_API_KEY": {"section": "llm", "secret": True},
    "ANTHROPIC_API_KEY": {"section": "llm", "secret": True},
    "GEMINI_API_KEY": {"section": "llm", "secret": True},
    "OPENROUTER_API_KEY": {"section": "llm", "secret": True},
    "OPENROUTER_BASE_URL": {"section": "llm", "secret": False},
    "NVIDIA_API_KEY": {"section": "llm", "secret": True},
    "NVIDIA_BASE_URL": {"section": "llm", "secret": False},
    # --- SMTP ---
    "SMTP_HOST": {"section": "smtp", "secret": False},
    "SMTP_PORT": {"section": "smtp", "secret": False},
    "SMTP_USERNAME": {"section": "smtp", "secret": False},
    "SMTP_PASSWORD": {"section": "smtp", "secret": True},
    "SMTP_USE_TLS": {"section": "smtp", "secret": False, "choices": ["true", "false"]},
    "SMTP_SENDER": {"section": "smtp", "secret": False},
    # --- Storage ---
    "STORAGE_DRIVER": {"section": "storage", "secret": False, "choices": ["LOCAL", "S3"]},
    "S3_BUCKET_NAME": {"section": "storage", "secret": False},
    "S3_ENDPOINT_URL": {"section": "storage", "secret": False},
    "AWS_ACCESS_KEY_ID": {"section": "storage", "secret": True},
    "AWS_SECRET_ACCESS_KEY": {"section": "storage", "secret": True},
    "AWS_REGION_NAME": {"section": "storage", "secret": False},
}

# Prefixes that, when touched, require the LLMProvider singleton to be rebuilt
# so the next call picks up new config (it caches model/provider env reads
# per-instance — see llm_provider.LLMProvider.__init__ / _resolve_model).
_LLM_RELOAD_PREFIXES = (
    "LLM_", "FAST_PROVIDER", "FAST_THINKER", "SLOW_PROVIDER", "SLOW_THINKER",
    "VISION_", "EMBEDDING_", "PRICING_",
    "OLLAMA_", "OPENAI_", "ANTHROPIC_", "GEMINI_", "OPENROUTER_", "NVIDIA_",
)


def load_settings_into_env(db: Session) -> None:
    """Apply all DB-stored settings to os.environ. Call once at startup.

    Skips empty/None values so .env defaults still apply for anything an
    admin has never configured.
    """
    import os

    rows = db.query(AppSetting).all()
    for row in rows:
        if row.key not in SETTINGS_REGISTRY:
            continue
        if row.value:
            os.environ[row.key] = row.value
    logger.info("Loaded %d admin-configured setting(s) from app_settings", len(rows))


def get_settings_for_admin(db: Session) -> Dict[str, Dict[str, Any]]:
    """Return current settings grouped by section, with secrets masked.

    Secret fields never return their value — only {"is_set": bool} — so a
    secret can never round-trip back to the browser once saved.
    """
    import os

    sections: Dict[str, Dict[str, Any]] = {}
    for key, meta in SETTINGS_REGISTRY.items():
        section = meta["section"]
        sections.setdefault(section, {})
        current = os.environ.get(key, "")
        if meta["secret"]:
            sections[section][key] = {
                "is_set": bool(current),
                "secret": True,
                "choices": meta.get("choices"),
            }
        else:
            sections[section][key] = {
                "value": current,
                "secret": False,
                "choices": meta.get("choices"),
            }
    return sections


def update_settings(
    db: Session,
    updates: Dict[str, str],
    admin_user_id: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Validate, persist, and apply a partial set of setting updates.

    Raises ValueError for any key not in SETTINGS_REGISTRY (callers should
    translate this to an HTTP 400).
    """
    import os

    unknown = [k for k in updates if k not in SETTINGS_REGISTRY]
    if unknown:
        raise ValueError(f"Unsupported setting key(s): {', '.join(unknown)}")

    updated_by_uuid: Optional[UUID] = None
    if admin_user_id:
        try:
            updated_by_uuid = UUID(str(admin_user_id))
        except ValueError:
            updated_by_uuid = None

    touched_keys = []
    for key, value in updates.items():
        meta = SETTINGS_REGISTRY[key]
        # Blank secret submission means "leave the stored value unchanged".
        if meta["secret"] and value == "":
            continue

        row = db.query(AppSetting).filter(AppSetting.key == key).one_or_none()
        if row is None:
            row = AppSetting(key=key)
            db.add(row)
        row.value = value
        row.updated_by_id = updated_by_uuid

        os.environ[key] = value
        touched_keys.append(key)

    db.commit()

    if any(k.startswith(_LLM_RELOAD_PREFIXES) for k in touched_keys):
        llm_provider.reset_provider()
        logger.info("Reset LLMProvider singleton after settings update: %s", touched_keys)

    return get_settings_for_admin(db)
