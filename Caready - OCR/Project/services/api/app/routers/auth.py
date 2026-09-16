"""Authentication: login, refresh, logout."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import CurrentUser
from app.enums import AuditAction, Role
from app.logging_config import get_logger
from app.models import RefreshToken, User
from app.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    refresh_token_expiry,
    verify_password,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = get_logger(__name__)
settings = get_settings()

#: Lock an account after this many consecutive failures. Generous enough not
#: to lock out an inspector fat-fingering a password in the yard, tight enough
#: to make online guessing impractical.
MAX_FAILED_LOGINS = 8
LOCKOUT_DURATION = timedelta(minutes=15)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    role: Role
    full_name: str
    #: Inspectors never receive price data. Sent so the client can lay out the
    #: right screens; enforcement is server-side regardless.
    can_read_prices: bool


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    branch_code: str | None
    capabilities: list[str]


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _issue_tokens(db: Session, user: User, request: Request, family_id: uuid.UUID | None = None) -> TokenResponse:
    from app.security import can_read_prices

    plaintext, token_hash = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id or uuid.uuid4(),
            expires_at=refresh_token_expiry(),
            user_agent=request.headers.get("User-Agent", "")[:512] or None,
            client_ip=_client_ip(request),
        )
    )
    access = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role,
        token_version=user.token_version,
        branch_code=user.branch_code,
    )
    return TokenResponse(
        access_token=access,
        refresh_token=plaintext,
        expires_in=settings.access_token_ttl_seconds,
        role=user.role,
        full_name=user.full_name,
        can_read_prices=can_read_prices(user.role),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    user = db.execute(select(User).where(User.email == payload.email.lower())).scalar_one_or_none()

    # Uniform failure response and timing: a distinguishable "no such user"
    # reply turns the login endpoint into an account enumeration oracle.
    generic_failure = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Email atau kata sandi salah"
    )

    if user is None:
        # Hash a dummy value so the response time does not reveal whether the
        # account exists.
        verify_password(payload.password, hash_password("dummy-timing-equaliser"))
        logger.info("login_failed", reason="unknown_email")
        raise generic_failure

    now = datetime.now(UTC)
    if user.locked_until and user.locked_until > now:
        logger.warning("login_blocked", reason="locked", user_id=str(user.id))
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Akun terkunci sementara karena terlalu banyak percobaan gagal",
        )

    if not user.is_active:
        logger.info("login_failed", reason="inactive", user_id=str(user.id))
        raise generic_failure

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + LOCKOUT_DURATION
            logger.warning("account_locked", user_id=str(user.id), failures=user.failed_login_count)
        logger.info("login_failed", reason="bad_password", user_id=str(user.id))
        raise generic_failure

    # Transparently upgrade the stored hash if argon2 parameters were tightened.
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now

    write_audit(
        db,
        entity_type="user",
        entity_id=user.id,
        action=AuditAction.LOGIN,
        actor=user,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    logger.info("login_succeeded", user_id=str(user.id), role=user.role.value)
    return _issue_tokens(db, user, request)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Rotate a refresh token.

    Reuse of an already-used token means the token leaked: the legitimate
    client would have moved on to its replacement. The whole family is revoked
    rather than just the replayed token, which logs out the attacker and the
    legitimate session alike - the safe outcome when we cannot tell them apart.
    """
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).scalar_one_or_none()

    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesi tidak berlaku")

    if stored is None:
        logger.warning("refresh_failed", reason="unknown_token")
        raise invalid

    now = datetime.now(UTC)

    if stored.used_at is not None:
        db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.family_id == stored.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason="reuse_detected")
        )
        logger.error(
            "refresh_token_reuse_detected",
            user_id=str(stored.user_id),
            family_id=str(stored.family_id),
        )
        raise invalid

    if stored.revoked_at is not None or stored.expires_at <= now:
        logger.info("refresh_failed", reason="revoked_or_expired")
        raise invalid

    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise invalid

    stored.used_at = now
    return _issue_tokens(db, user, request, family_id=stored.family_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: RefreshRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash)).scalar_one_or_none()
    if stored is not None and stored.user_id == user.id:
        db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.family_id == stored.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason="logout")
        )
    logger.info("logout", user_id=str(user.id))


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser) -> MeResponse:
    from app.security import capabilities_for

    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        branch_code=user.branch_code,
        capabilities=sorted(c.value for c in capabilities_for(user.role)),
    )
