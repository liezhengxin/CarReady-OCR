"""Append-only audit trail, status transitions, PII access log, and job runs (§8.6, §10).

Every table here is append-only and is protected by a database trigger
installed in the baseline migration. An audit trail the application can
rewrite is not an audit trail, so enforcement does not rely on application
discipline alone.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import AuditAction, JobStatus, JobType, UnitStatus
from app.models.base import AppendOnlyMixin, Base, enum_column, uuid_pk

#: Tables the append-only trigger is installed on. The migration reads this
#: list, so adding a table here is enough to protect it.
APPEND_ONLY_TABLES: tuple[str, ...] = (
    "audit_log",
    "unit_status_transitions",
    "pii_access_log",
)


class AuditLog(Base, AppendOnlyMixin):
    """Append-only record of every material change.

    Deliberately denormalised: `actor_email` and `actor_role` are copied in at
    write time rather than joined at read time, so the record still reads
    correctly after a user is renamed, has their role changed, or is deleted.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        sa.Index("ix_audit_log_entity", "entity_type", "entity_id"),
        sa.Index("ix_audit_log_actor_created", "actor_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    entity_type: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[AuditAction] = mapped_column(enum_column(AuditAction), nullable=False, index=True)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Snapshotted at write time - see class docstring.
    actor_email: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Mandatory for overrides and rejections; enforced in the service layer
    #: where a specific error message can be produced.
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    client_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    #: Correlates every row written during one request or job.
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)


class UnitStatusTransition(Base, AppendOnlyMixin):
    """Append-only state machine history (§8.6).

    DRAFT -> ICR_DONE -> GRADED -> PRICED -> PENDING_APPROVAL -> APPROVED | REJECTED
    """

    __tablename__ = "unit_status_transitions"
    __table_args__ = (sa.Index("ix_unit_transitions_unit_created", "unit_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Null only for the initial DRAFT row.
    from_status: Mapped[UnitStatus | None] = mapped_column(enum_column(UnitStatus), nullable=True)
    to_status: Mapped[UnitStatus] = mapped_column(enum_column(UnitStatus), nullable=False, index=True)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    #: True when a background job advanced the state rather than a person. No
    #: AI-generated price is ever published this way - the transition into
    #: APPROVED is always actor-driven.
    automated: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())

    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Hard blocks that were evaluated at this transition. Recorded even when
    #: empty, so the absence of a block is itself evidenced.
    blockers_evaluated: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    blockers_overridden: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)


class PiiAccessLog(Base, AppendOnlyMixin):
    """Every unmasking of a PII field (§10).

    Written before the plaintext reaches the response. A failed authorisation
    is logged too - an attempt to unmask is itself worth recording.
    """

    __tablename__ = "pii_access_log"
    __table_args__ = (sa.Index("ix_pii_access_actor_created", "actor_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_email: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Dotted field path, e.g. "unit_stnk_data.nama_pemilik".
    field_path: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    #: `general` or `specific` per config/pdp.yaml. Specific personal data
    #: additionally requires a typed justification.
    pii_class: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    purpose: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    justification: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    granted: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true(), index=True)
    denial_reason: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    client_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)


class JobRun(Base):
    """Background job execution record.

    Not append-only - a running job legitimately updates its own row. The
    audit trail for what the job *did* lives in `audit_log`.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        sa.Index("ix_job_runs_type_status", "job_type", "status"),
        sa.Index("ix_job_runs_unit_created", "unit_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_type: Mapped[JobType] = mapped_column(enum_column(JobType), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus), nullable=False, server_default=JobStatus.QUEUED.value, index=True
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rq_job_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)

    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Truncated traceback. Useful in the dashboard without needing log access.
    error_detail: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    attempt: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default=sa.text("1"))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
