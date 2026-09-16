"""Password hashing, JWT issuance, and capability checks.

Design points worth stating:

  - Access tokens carry `token_version`. Bumping a user's version invalidates
    every outstanding access token immediately - needed for a role change or a
    deactivation to take effect before the token's natural expiry.

  - Refresh tokens rotate and are tracked by family. Reuse of an already-used
    token is treated as theft and revokes the whole family rather than just
    the replayed token.

  - Capabilities, not roles, are checked at the call site. `require(...)` takes
    a capability so a future role change is a table edit in enums.py rather
    than a hunt through route handlers.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type

from app.config import get_settings
from app.enums import ROLE_CAPABILITIES, Capability, Role

_settings = get_settings()

_hasher = PasswordHasher(
    time_cost=_settings.argon2_time_cost,
    memory_cost=_settings.argon2_memory_cost_kib,
    parallelism=_settings.argon2_parallelism,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, plaintext)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than current config.

    Checked on successful login so tightening the argon2 parameters upgrades
    existing users transparently, rather than only applying to new ones.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------


class TokenError(Exception):
    pass


def create_access_token(
    *, user_id: uuid.UUID, email: str, role: Role, token_version: int, branch_code: str | None = None
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role.value,
        "tv": token_version,
        "branch": branch_code,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=_settings.access_token_ttl_seconds)).timestamp()),
        "typ": "access",
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            _settings.jwt_secret,
            algorithms=[_settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token_invalid") from exc
    if payload.get("typ") != "access":
        raise TokenError("wrong_token_type")
    return payload


def generate_refresh_token() -> tuple[str, str]:
    """Return (plaintext, sha256). Only the hash is ever stored."""
    plaintext = secrets.token_urlsafe(48)
    return plaintext, hash_refresh_token(plaintext)


def hash_refresh_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=_settings.refresh_token_ttl_seconds)


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------


def capabilities_for(role: Role) -> frozenset[Capability]:
    return ROLE_CAPABILITIES.get(role, frozenset())


def has_capability(role: Role, capability: Capability) -> bool:
    return capability in capabilities_for(role)


def can_read_prices(role: Role) -> bool:
    """Inspectors cannot see prices.

    This is a business control, not a UI preference: an inspector who can see
    the price a unit is heading toward has an incentive to shade damage
    reporting toward it. Enforced server-side - price fields are omitted from
    the serialised response, not merely hidden by the client.
    """
    return has_capability(role, Capability.UNIT_READ_PRICE)
