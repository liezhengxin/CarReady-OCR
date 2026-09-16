"""Symmetric encryption for PII columns at rest (§10).

Fernet (AES-128-CBC + HMAC-SHA256) via `cryptography`. Chosen over raw AES
because it is authenticated and misuse-resistant; we are protecting against
database disclosure, not against an attacker with application memory access.

Key management: the key comes from the environment. In production it should be
delivered by a secrets manager and rotated on a schedule. Rotation is
supported through `PII_ENCRYPTION_KEYS` - a comma-separated list where the
first entry encrypts and every entry is tried on decrypt.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.config import get_settings

logger = logging.getLogger(__name__)


class EncryptionNotConfiguredError(RuntimeError):
    pass


def _derive_fernet_key(raw: str) -> bytes:
    """Accept either a real Fernet key or an arbitrary passphrase.

    A passphrase is stretched with SHA-256 so that a developer .env value
    works out of the box, while a properly generated 32-byte key passes
    through unchanged.
    """
    raw = raw.strip()
    try:
        candidate = base64.urlsafe_b64decode(raw.encode())
        if len(candidate) == 32:
            return raw.encode()
    except Exception:  # noqa: BLE001 - not a valid Fernet key, fall through
        pass
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _cipher() -> MultiFernet:
    settings = get_settings()
    keys = [k for k in settings.pii_encryption_keys.split(",") if k.strip()]
    if not keys:
        raise EncryptionNotConfiguredError(
            "PII_ENCRYPTION_KEYS is empty. Refusing to start - PII columns "
            "cannot be written without an encryption key."
        )
    return MultiFernet([Fernet(_derive_fernet_key(k)) for k in keys])


def encrypt_text(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext: str) -> str:
    """Decrypt, or return a redaction marker if the key no longer matches.

    Raising here would make an entire unit unreadable after a botched key
    rotation, including its non-PII fields. Returning a marker keeps the
    record usable and makes the problem visible in the UI and the logs.
    """
    try:
        return _cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("pii_decrypt_failed", extra={"reason": "invalid_token_or_rotated_key"})
        return "— tidak dapat didekripsi —"


def rotate_ciphertext(ciphertext: str) -> str:
    """Re-encrypt under the current primary key. Used by the rotation job."""
    return _cipher().rotate(ciphertext.encode("ascii")).decode("ascii")


def generate_key() -> str:
    """Emit a fresh Fernet key. Used by `make gen-key` and documented in .env.example."""
    return Fernet.generate_key().decode("ascii")
