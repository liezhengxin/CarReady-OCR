"""Audit trail writing (§8.6, §10).

One place that writes audit rows, so the actor snapshot, request correlation,
and PII redaction are applied consistently rather than remembered at each call
site.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.enums import AuditAction
from app.logging_config import REDACT_KEY_SUFFIXES, request_id_ctx
from app.models import AuditLog, PiiAccessLog, User

REDACTED = "[REDACTED]"


def _redact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip PII values from a before/after snapshot.

    The audit log records THAT a PII field changed and by whom; the value
    itself stays in the encrypted column. Copying plaintext PII into an
    append-only table would create a second, unerasable copy - which is
    precisely what the retention policy exists to prevent.
    """
    if payload is None:
        return None
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if any(key.lower().endswith(suffix) for suffix in REDACT_KEY_SUFFIXES):
            out[key] = REDACTED
        elif isinstance(value, dict):
            out[key] = _redact(value)
        else:
            out[key] = value
    return out


def write_audit(
    db: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action: AuditAction,
    actor: User | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append an audit row.

    Added to the session but not committed - the audit row and the change it
    describes must land in the same transaction, or a rollback leaves a record
    of something that never happened.
    """
    row = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor.id if actor else None,
        # Snapshotted rather than joined, so the record still reads correctly
        # after a rename, a role change, or a deletion.
        actor_email=actor.email if actor else None,
        actor_role=actor.role.value if actor else None,
        before=_redact(before),
        after=_redact(after),
        reason=reason,
        client_ip=client_ip,
        user_agent=(user_agent or "")[:512] or None,
        request_id=request_id_ctx.get(),
    )
    db.add(row)
    return row


def write_pii_access(
    db: Session,
    *,
    actor: User | None,
    unit_id: uuid.UUID | None,
    field_path: str,
    pii_class: str,
    granted: bool,
    purpose: str | None = None,
    justification: str | None = None,
    denial_reason: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> PiiAccessLog:
    """Record an unmasking attempt.

    Called BEFORE the plaintext reaches the response, and for denied attempts
    too - an attempt to unmask is itself worth recording.
    """
    row = PiiAccessLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        actor_role=actor.role.value if actor else None,
        unit_id=unit_id,
        field_path=field_path,
        pii_class=pii_class,
        purpose=purpose,
        justification=justification,
        granted=granted,
        denial_reason=denial_reason,
        client_ip=client_ip,
        user_agent=(user_agent or "")[:512] or None,
        request_id=request_id_ctx.get(),
    )
    db.add(row)
    return row
