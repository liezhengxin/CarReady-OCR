"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Set before any app module imports, so Settings picks these up rather than a
# developer's real .env.
os.environ.setdefault("ENVIRONMENT", "ci")
os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("PII_ENCRYPTION_KEYS", "test-only-encryption-passphrase")
os.environ.setdefault("SYNTHETIC_DATA_MODE", "true")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal, check_database  # noqa: E402
from app.enums import Role  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

requires_db = pytest.mark.skipif(
    not check_database(),
    reason="no database available; run with DATABASE_URL pointing at a migrated database",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db() -> Iterator[Session]:
    """A session that rolls back at the end of the test.

    Rollback rather than truncate: it is faster, and it leaves the seeded data
    a developer may be working against untouched.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def make_user(db: Session):
    created: list[User] = []

    def _make(role: Role, email: str | None = None, password: str = "test-password-123") -> User:
        user = User(
            email=email or f"{role.value}-{len(created)}@test.local",
            full_name=f"Test {role.value}",
            password_hash=hash_password(password),
            role=role,
        )
        db.add(user)
        db.flush()
        created.append(user)
        return user

    yield _make

    for user in created:
        db.delete(user)
    db.flush()
