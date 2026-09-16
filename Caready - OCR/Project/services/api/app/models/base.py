"""Declarative base, shared column types, and mixins."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.crypto import decrypt_text, encrypt_text

#: Naming convention so Alembic autogenerate produces stable, diffable names
#: for constraints and indexes. Without this, autogenerate emits anonymous
#: constraint names and every migration churns.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
    }


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def enum_column(enum_cls: type, **kwargs: Any) -> sa.Enum:
    """A VARCHAR + CHECK constraint column for a Python enum.

    Deliberately NOT a native PostgreSQL ENUM type: adding a value to a native
    enum requires ALTER TYPE, which does not run inside a transaction on older
    PostgreSQL and complicates rollback. A checked VARCHAR gives the same
    integrity with a migration that is a plain constraint swap.

    `values_callable` is required - without it SQLAlchemy persists the enum
    *name* (`INSPECTOR`) rather than its *value* (`inspector`), which would
    silently diverge from every YAML config file and API payload.
    """
    return sa.Enum(
        enum_cls,
        name=f"{_snake(enum_cls.__name__)}_enum",
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
        **kwargs,
    )


class EncryptedText(sa.types.TypeDecorator):
    """Application-level encryption for a PII column (§10).

    Ciphertext is stored as text. The key is supplied by the environment and
    is never written to the database, so a database dump alone does not
    disclose personal data.

    Trade-off accepted: an encrypted column cannot be indexed, sorted, or
    searched with LIKE. Every field encrypted here is one we only ever read
    back per-unit, never query across. `nomor_registrasi` is deliberately NOT
    encrypted for exactly this reason - it is an operational lookup key - and
    is protected by masking and access logging instead.
    """

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return encrypt_text(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return decrypt_text(value)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=sa.text("gen_random_uuid()")
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()
    )


class AppendOnlyMixin:
    """Marker for tables that must never be updated or deleted.

    Enforcement is at the database level via a trigger installed in the
    baseline migration, not only in application code - an append-only audit
    trail that the application can rewrite is not an audit trail.
    """

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )
