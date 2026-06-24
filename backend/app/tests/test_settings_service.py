"""
Tests for backend/app/services/settings_service.py — admin-editable runtime
settings (LLM, SMTP, Storage).
"""

import os
import uuid
from unittest import mock

import pytest

from app.services import settings_service
from app.services.settings_service import (
    SETTINGS_REGISTRY,
    get_settings_for_admin,
    load_settings_into_env,
    update_settings,
)
from app.models import AppSetting


TEST_ENCRYPTION_KEY = "gdM1BemlB1hZLDqKATsfQNANKHQQ_HQH7F61aPJh9bU="


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    for key in SETTINGS_REGISTRY:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def mock_db():
    return mock.MagicMock()


def _row(key, value):
    row = mock.MagicMock(spec=AppSetting)
    row.key = key
    row.value = value
    return row


# ---------------------------------------------------------------------------
# load_settings_into_env
# ---------------------------------------------------------------------------


class TestLoadSettingsIntoEnv:
    def test_applies_known_keys_to_environ(self, mock_db):
        mock_db.query.return_value.all.return_value = [
            _row("LLM_PROVIDER", "anthropic"),
            _row("SMTP_HOST", "smtp.example.com"),
        ]
        load_settings_into_env(mock_db)
        assert os.environ["LLM_PROVIDER"] == "anthropic"
        assert os.environ["SMTP_HOST"] == "smtp.example.com"

    def test_skips_unknown_keys(self, mock_db, monkeypatch):
        monkeypatch.delenv("JWT_SECRET", raising=False)
        mock_db.query.return_value.all.return_value = [_row("JWT_SECRET", "leaked")]
        load_settings_into_env(mock_db)
        assert "JWT_SECRET" not in os.environ

    def test_skips_empty_values(self, mock_db):
        mock_db.query.return_value.all.return_value = [_row("LLM_PROVIDER", "")]
        load_settings_into_env(mock_db)
        assert "LLM_PROVIDER" not in os.environ


# ---------------------------------------------------------------------------
# get_settings_for_admin
# ---------------------------------------------------------------------------


class TestGetSettingsForAdmin:
    def test_groups_by_section(self, mock_db):
        result = get_settings_for_admin(mock_db)
        assert set(result.keys()) == {"llm", "smtp", "storage"}

    def test_secret_fields_never_return_value(self, mock_db, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret")
        result = get_settings_for_admin(mock_db)
        entry = result["llm"]["OPENAI_API_KEY"]
        assert entry["secret"] is True
        assert entry["is_set"] is True
        assert "value" not in entry
        assert "sk-super-secret" not in str(entry)

    def test_secret_field_is_set_false_when_unset(self, mock_db):
        result = get_settings_for_admin(mock_db)
        entry = result["llm"]["OPENAI_API_KEY"]
        assert entry["is_set"] is False

    def test_non_secret_field_returns_value(self, mock_db, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "mail.example.com")
        result = get_settings_for_admin(mock_db)
        entry = result["smtp"]["SMTP_HOST"]
        assert entry["secret"] is False
        assert entry["value"] == "mail.example.com"

    def test_choices_surfaced_when_present(self, mock_db):
        result = get_settings_for_admin(mock_db)
        assert result["llm"]["LLM_PROVIDER"]["choices"] == settings_service._PROVIDER_CHOICES


# ---------------------------------------------------------------------------
# update_settings
# ---------------------------------------------------------------------------


class TestUpdateSettings:
    def test_rejects_unknown_key(self, mock_db):
        with pytest.raises(ValueError, match="JWT_SECRET"):
            update_settings(mock_db, {"JWT_SECRET": "newsecret"})

    def test_upserts_new_row(self, mock_db):
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        update_settings(mock_db, {"LLM_PROVIDER": "openai"})
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.key == "LLM_PROVIDER"
        assert added.value == "openai"
        mock_db.commit.assert_called_once()
        assert os.environ["LLM_PROVIDER"] == "openai"

    def test_updates_existing_row(self, mock_db):
        existing = AppSetting(key="LLM_PROVIDER", value="ollama")
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = existing
        update_settings(mock_db, {"LLM_PROVIDER": "anthropic"})
        assert existing.value == "anthropic"
        mock_db.add.assert_not_called()

    def test_blank_secret_means_unchanged(self, mock_db):
        update_settings(mock_db, {"OPENAI_API_KEY": ""})
        mock_db.add.assert_not_called()
        mock_db.query.assert_not_called()
        assert "OPENAI_API_KEY" not in os.environ

    def test_non_empty_secret_is_persisted(self, mock_db):
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        update_settings(mock_db, {"OPENAI_API_KEY": "sk-new-key"})
        added = mock_db.add.call_args[0][0]
        assert added.value == "sk-new-key"
        assert os.environ["OPENAI_API_KEY"] == "sk-new-key"

    def test_sets_updated_by_id_when_valid_uuid(self, mock_db):
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        admin_id = str(uuid.uuid4())
        update_settings(mock_db, {"LLM_PROVIDER": "openai"}, admin_user_id=admin_id)
        added = mock_db.add.call_args[0][0]
        assert str(added.updated_by_id) == admin_id

    def test_invalid_admin_id_does_not_raise(self, mock_db):
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        update_settings(mock_db, {"LLM_PROVIDER": "openai"}, admin_user_id="not-a-uuid")
        added = mock_db.add.call_args[0][0]
        assert added.updated_by_id is None

    def test_llm_key_triggers_provider_reset(self, mock_db):
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        with mock.patch("app.services.settings_service.llm_provider.reset_provider") as mock_reset:
            update_settings(mock_db, {"FAST_THINKER_MODEL": "gpt-5"})
            mock_reset.assert_called_once()

    def test_smtp_key_does_not_trigger_provider_reset(self, mock_db):
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        with mock.patch("app.services.settings_service.llm_provider.reset_provider") as mock_reset:
            update_settings(mock_db, {"SMTP_HOST": "mail.example.com"})
            mock_reset.assert_not_called()

    def test_returns_refreshed_settings_payload(self, mock_db):
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        result = update_settings(mock_db, {"LLM_PROVIDER": "openai"})
        assert result["llm"]["LLM_PROVIDER"]["value"] == "openai"
