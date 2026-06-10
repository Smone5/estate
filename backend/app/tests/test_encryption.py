"""
Tests for T03 — AES-Fernet Encryption Decorator.

Verifies:
- EncryptedJSON TypeDecorator encrypts values on bind and decrypts on read
- EncryptedJSON handles None values gracefully
- EncryptedJSON raises ValueError when ENCRYPTION_KEY is not set (on first use)
- EncryptedJSON round-trips dict, list, and str values correctly
- Models use EncryptedJSON on the correct columns:
    audit_logs.state_snapshot
    chat_messages.message_text
    valuations.reasoning
"""

import os
import json

import pytest
from cryptography.fernet import Fernet

from app.encryption import EncryptedJSON
from app.models import AuditLog, ChatMessage, Valuation


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def set_encryption_key():
    """Set a valid Fernet key in the environment for all tests."""
    key = Fernet.generate_key().decode()
    os.environ["ENCRYPTION_KEY"] = key
    yield
    os.environ.pop("ENCRYPTION_KEY", None)


@pytest.fixture
def fernet_instance():
    """Return a Fernet instance matching the test ENCRYPTION_KEY."""
    return Fernet(os.environ["ENCRYPTION_KEY"].encode())


# ═════════════════════════════════════════════════════════════════════
# EncryptedJSON unit tests
# ═════════════════════════════════════════════════════════════════════


class TestEncryptedJSONInit:
    """Verify EncryptedJSON construction (lazy — no key check at init)."""

    def test_creates_instance_without_key(self):
        """EncryptedJSON can be constructed without ENCRYPTION_KEY (lazy init)."""
        os.environ.pop("ENCRYPTION_KEY", None)
        decorator = EncryptedJSON()
        assert decorator is not None

    def test_raises_value_error_on_first_use_without_key(self):
        """EncryptedJSON raises ValueError on first bind/result without key."""
        os.environ.pop("ENCRYPTION_KEY", None)
        decorator = EncryptedJSON()
        with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
            decorator.process_bind_param({"test": "data"}, None)


class TestEncryptedJSONBindParam:
    """Verify process_bind_param encrypts values."""

    def test_returns_none_for_none_input(self):
        decorator = EncryptedJSON()
        assert decorator.process_bind_param(None, None) is None

    def test_returns_ciphertext_for_dict(self, fernet_instance):
        decorator = EncryptedJSON()
        value = {"key": "sensitive data", "nested": {"a": 1}}
        result = decorator.process_bind_param(value, None)
        assert result is not None
        assert isinstance(result, str)
        # Verify it's actually encrypted (not plaintext JSON)
        assert "sensitive data" not in result
        # Verify it can be decrypted back
        decrypted = fernet_instance.decrypt(result.encode()).decode()
        assert json.loads(decrypted) == value

    def test_returns_ciphertext_for_list(self, fernet_instance):
        decorator = EncryptedJSON()
        value = ["item1", "item2", {"nested": True}]
        result = decorator.process_bind_param(value, None)
        assert result is not None
        decrypted = fernet_instance.decrypt(result.encode()).decode()
        assert json.loads(decrypted) == value

    def test_returns_ciphertext_for_string(self, fernet_instance):
        decorator = EncryptedJSON()
        value = "plain text message"
        result = decorator.process_bind_param(value, None)
        assert result is not None
        decrypted = fernet_instance.decrypt(result.encode()).decode()
        assert json.loads(decrypted) == value


class TestEncryptedJSONResultValue:
    """Verify process_result_value decrypts values."""

    def test_returns_none_for_none_input(self):
        decorator = EncryptedJSON()
        assert decorator.process_result_value(None, None) is None

    def test_returns_plaintext_for_valid_ciphertext(self, fernet_instance):
        decorator = EncryptedJSON()
        original = {"key": "sensitive data"}
        ciphertext = fernet_instance.encrypt(
            json.dumps(original).encode()
        ).decode()
        result = decorator.process_result_value(ciphertext, None)
        assert result == original

    def test_round_trip_dict(self):
        decorator = EncryptedJSON()
        original = {"user": "alice", "role": "heir", "score": 100}
        ciphertext = decorator.process_bind_param(original, None)
        decrypted = decorator.process_result_value(ciphertext, None)
        assert decrypted == original

    def test_round_trip_list(self):
        decorator = EncryptedJSON()
        original = ["a", "b", "c"]
        ciphertext = decorator.process_bind_param(original, None)
        decrypted = decorator.process_result_value(ciphertext, None)
        assert decrypted == original

    def test_round_trip_string(self):
        decorator = EncryptedJSON()
        original = "This is a sensitive message."
        ciphertext = decorator.process_bind_param(original, None)
        decrypted = decorator.process_result_value(ciphertext, None)
        assert decrypted == original


# ═════════════════════════════════════════════════════════════════════
# Model column type verification
# ═════════════════════════════════════════════════════════════════════


class TestModelEncryptedColumns:
    """Verify that the correct model columns use EncryptedJSON."""

    def test_audit_log_state_snapshot_is_encrypted(self):
        col = AuditLog.__table__.columns["state_snapshot"]
        assert isinstance(col.type, EncryptedJSON)

    def test_chat_message_message_text_is_encrypted(self):
        col = ChatMessage.__table__.columns["message_text"]
        assert isinstance(col.type, EncryptedJSON)

    def test_valuation_reasoning_is_encrypted(self):
        col = Valuation.__table__.columns["reasoning"]
        assert isinstance(col.type, EncryptedJSON)

    def test_chat_message_scrubbed_text_is_not_encrypted(self):
        """scrubbed_text must remain plaintext per DB Spec §5."""
        from sqlalchemy.types import Text
        col = ChatMessage.__table__.columns["scrubbed_text"]
        assert isinstance(col.type, Text)
        assert not isinstance(col.type, EncryptedJSON)
