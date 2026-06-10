"""
AES-Fernet field-level encryption decorator for SQLAlchemy models.

Per DB Spec §5: Implements EncryptedJSON TypeDecorator that transparently
encrypts/decrypts sensitive columns at rest using Fernet symmetric encryption.

Applied to:
  - audit_logs.state_snapshot  (encrypted JSON string)
  - chat_messages.message_text (encrypted raw chat text)
  - valuations.reasoning       (encrypted heir sentimental reasons)
"""

import json
import os

from cryptography.fernet import Fernet
from sqlalchemy.types import TypeDecorator, Text


def _get_fernet():
    """Lazily load the Fernet cipher from ENCRYPTION_KEY.

    Deferred to first use so that model classes can be imported without
    the environment variable being set (e.g. during test collection).
    """
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY environment variable is not set.")
    return Fernet(key.encode())


class EncryptedJSON(TypeDecorator):
    """Transparently encrypts JSON-serializable values at rest using AES-Fernet.

    Stores ciphertext in a Text column. On read, decrypts and deserializes
    back to the original Python object (dict, list, str, etc.).

    Usage:
        state_snapshot = Column(EncryptedJSON, nullable=False)
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt and serialize the value before writing to the database."""
        if value is None:
            return None
        fernet = _get_fernet()
        serialized = json.dumps(value, default=str)
        return fernet.encrypt(serialized.encode()).decode()

    def process_result_value(self, value, dialect):
        """Decrypt and deserialize the value after reading from the database."""
        if value is None:
            return None
        fernet = _get_fernet()
        decrypted = fernet.decrypt(value.encode()).decode()
        return json.loads(decrypted)
