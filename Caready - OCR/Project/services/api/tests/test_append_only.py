"""The audit trail must be append-only at the database level.

Enforcing this only in Python would mean the guarantee holds exactly as long as
every future code path remembers it. These tests assert the trigger is
installed and actually refuses mutations - an audit trail the application can
rewrite is not an audit trail.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import append_only_purge_allowed
from app.enums import AuditAction
from app.models import APPEND_ONLY_TABLES, AuditLog

from .conftest import requires_db

pytestmark = [requires_db, pytest.mark.integration]


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_trigger_is_installed(db: Session, table: str) -> None:
    result = db.execute(
        text(
            "SELECT tgname FROM pg_trigger "
            "WHERE tgrelid = :table::regclass AND NOT tgisinternal"
        ),
        {"table": table},
    ).scalars().all()
    assert f"trg_{table}_append_only" in result


def _insert_audit_row(db: Session) -> AuditLog:
    row = AuditLog(
        entity_type="test",
        entity_id=uuid.uuid4(),
        action=AuditAction.CREATE,
        actor_email="test@test.local",
        actor_role="admin",
    )
    db.add(row)
    db.flush()
    return row


def test_update_is_rejected(db: Session) -> None:
    row = _insert_audit_row(db)
    with pytest.raises(DBAPIError) as exc:
        db.execute(text("UPDATE audit_log SET reason = 'tampered' WHERE id = :id"), {"id": row.id})
        db.flush()
    assert "append-only" in str(exc.value).lower()
    db.rollback()


def test_delete_is_rejected(db: Session) -> None:
    row = _insert_audit_row(db)
    with pytest.raises(DBAPIError) as exc:
        db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row.id})
        db.flush()
    assert "append-only" in str(exc.value).lower()
    db.rollback()


def test_retention_purge_may_delete(db: Session) -> None:
    """The one legitimate bypass: the PDP retention job (§10).

    Scoped to the transaction via SET LOCAL, so the permission cannot leak into
    unrelated work on the same connection.
    """
    row = _insert_audit_row(db)
    row_id = row.id
    with append_only_purge_allowed(db):
        db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row_id})
        db.flush()
    remaining = db.execute(text("SELECT count(*) FROM audit_log WHERE id = :id"), {"id": row_id}).scalar()
    assert remaining == 0
    db.rollback()


def test_purge_permission_does_not_outlive_its_scope(db: Session) -> None:
    """After the context manager exits, deletes must be refused again."""
    row = _insert_audit_row(db)
    with append_only_purge_allowed(db):
        pass
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row.id})
        db.flush()
    db.rollback()


def test_purge_permission_does_not_allow_update(db: Session) -> None:
    """The escape hatch is for deletion only. Rewriting history is never
    legitimate, even during a purge."""
    row = _insert_audit_row(db)
    with pytest.raises(DBAPIError), append_only_purge_allowed(db):
        db.execute(text("UPDATE audit_log SET reason = 'rewritten' WHERE id = :id"), {"id": row.id})
        db.flush()
    db.rollback()
