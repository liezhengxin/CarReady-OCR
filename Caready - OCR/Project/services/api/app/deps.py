"""FastAPI dependencies: current user, capability guards."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.enums import Capability, Role
from app.logging_config import actor_id_ctx, get_logger
from app.models import User
from app.security import TokenError, decode_access_token, has_capability

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tidak terautentikasi",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Akun tidak aktif")

    # A role change or a forced logout bumps token_version, which invalidates
    # outstanding access tokens without waiting for them to expire.
    if payload.get("tv") != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi tidak berlaku lagi, silakan masuk kembali",
        )

    actor_id_ctx.set(str(user.id))
    request.state.user = user
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(*capabilities: Capability) -> Callable[..., User]:
    """Guard a route on one or more capabilities.

    Capability-based rather than role-based so that a permission change is an
    edit to ROLE_CAPABILITIES in enums.py, not a search through route
    decorators for every place a role name was hardcoded.
    """

    def dependency(user: CurrentUser) -> User:
        missing = [c for c in capabilities if not has_capability(user.role, c)]
        if missing:
            logger.warning(
                "authorization_denied",
                required=[c.value for c in capabilities],
                missing=[c.value for c in missing],
                role=user.role.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki izin untuk tindakan ini",
            )
        return user

    return dependency


def require_role(*roles: Role) -> Callable[..., User]:
    """Guard on an explicit role.

    Prefer `require(Capability...)`. This exists for the handful of endpoints
    that are genuinely about who someone is rather than what they may do -
    admin user management, for instance.
    """

    def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki izin untuk tindakan ini",
            )
        return user

    return dependency
