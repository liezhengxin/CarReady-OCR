"""Users, sessions, and refresh tokens."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import Role
from app.models.base import Base, TimestampMixin, enum_column, uuid_pk


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    #: argon2id. Never a reversible encoding.
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[Role] = mapped_column(enum_column(Role), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    #: Branch / auction location this user operates at. Used for scoping the
    #: dashboard, not for permissions.
    branch_code: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Consecutive failed logins; reset on success. Drives lockout.
    failed_login_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Bumped to invalidate every outstanding access token for this user
    #: (role change, deactivation, credential reset). Access tokens carry this
    #: value and are rejected when it no longer matches.
    token_version: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} role={self.role}>"


class RefreshToken(Base):
    """Opaque refresh token, stored hashed.

    Rotating: each refresh issues a new token and marks the old one used. A
    reuse of an already-used token is treated as theft and revokes the whole
    family via `family_id`.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: sha256 of the token. The plaintext is only ever in the client's hands.
    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True, index=True)
    #: All tokens descended from one login share a family. Reuse detection
    #: revokes the family, not just the token.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_active(self) -> bool:
        return self.used_at is None and self.revoked_at is None
