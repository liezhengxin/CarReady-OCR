"""ICR/OCR extractions, cross-check results, and plate condition (§5)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import (
    CheckSeverity,
    CheckVerdict,
    CrossCheckType,
    OcrProviderName,
    PlateCondition,
)
from app.models.base import Base, TimestampMixin, enum_column, uuid_pk


class OcrExtraction(Base, TimestampMixin):
    """One provider call against one photo.

    The raw provider response is persisted verbatim. When a field is disputed
    months later, the raw response is what settles it - a parsed summary is
    not enough, because the parser itself may have been the problem.
    """

    __tablename__ = "ocr_extractions"
    __table_args__ = (sa.Index("ix_ocr_extractions_photo_provider", "photo_id", "provider"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[OcrProviderName] = mapped_column(enum_column(OcrProviderName), nullable=False)
    provider_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    #: Which extract_* method produced this row.
    extraction_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)

    #: Parsed field values, keyed by canonical field name.
    fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Per-field confidence, same keys as `fields`. Required by §5.1.
    field_confidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Unmodified provider payload. Audit record.
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: True when this call was made against a redacted copy of the image
    #: because the provider is external and PDP clearance was not granted.
    pii_redacted_before_call: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    external_provider: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())

    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    succeeded: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: Set when a later extraction supersedes this one (re-run after a retake).
    superseded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    photo: Mapped["Photo"] = relationship(back_populates="ocr_extractions")  # noqa: F821


class CrossCheckResult(Base, TimestampMixin):
    """One typed cross-check outcome (§5.4).

    Checks never auto-correct. A check can only produce a verdict and a
    severity; acting on it is a human decision or an explicit state-machine
    rule.
    """

    __tablename__ = "cross_check_results"
    __table_args__ = (
        sa.Index("ix_cross_check_unit_type", "unit_id", "check_type"),
        sa.Index("ix_cross_check_severity_open", "severity", "resolved_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    check_type: Mapped[CrossCheckType] = mapped_column(enum_column(CrossCheckType), nullable=False)
    verdict: Mapped[CheckVerdict] = mapped_column(enum_column(CheckVerdict), nullable=False, index=True)
    severity: Mapped[CheckSeverity] = mapped_column(enum_column(CheckSeverity), nullable=False, index=True)

    #: Human-readable explanation, in Bahasa Indonesia, shown in the dashboard.
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    #: Structured evidence: the compared values, distances, thresholds used.
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Version of config/crosschecks.yaml that produced this verdict, so an
    #: old result remains interpretable after a threshold change.
    ruleset_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    #: Recorded whenever a comparison only matched after character
    #: normalisation (O->0, I->1, Q->0). A normalised match is materially
    #: weaker evidence than an exact one and must stay distinguishable.
    normalisation_applied: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )

    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    #: An appraiser may accept a flagged check, but never delete it.
    resolution_action: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    @property
    def is_blocking(self) -> bool:
        return self.severity == CheckSeverity.BLOCKER and self.resolved_at is None


class PlateConditionAssessment(Base, TimestampMixin):
    """Classification of the VIN plate / etching image (§5.5).

    TAMPERED_SUSPECTED is a fraud signal, not a cosmetic one: it hard-blocks
    auto-approval and forces appraiser review.
    """

    __tablename__ = "plate_condition_assessments"

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    classification: Mapped[PlateCondition] = mapped_column(
        enum_column(PlateCondition), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False)
    #: Free-text rationale from the provider. Shown to the appraiser - a
    #: classification without a reason is not actionable.
    rationale: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    provider: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    provider_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: Appraiser override. The AI classification is never overwritten.
    override_classification: Mapped[PlateCondition | None] = mapped_column(
        enum_column(PlateCondition), nullable=True
    )
    override_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    override_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    override_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    @property
    def effective_classification(self) -> PlateCondition:
        return self.override_classification or self.classification


class VinDecodeResult(Base, TimestampMixin):
    """Optional VIN enrichment (§5.3).

    Never authoritative. The STNK wins every disagreement; this row exists to
    raise a flag and to accumulate the empirical VDS->variant evidence.
    """

    __tablename__ = "vin_decode_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    vin: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    wmi: Mapped[str | None] = mapped_column(sa.String(3), nullable=True, index=True)
    vds: Mapped[str | None] = mapped_column(sa.String(6), nullable=True)
    #: Decoded from the WMI table. Null when the prefix is unknown, which is an
    #: expected outcome for many domestic CKD units and is reported as INFO.
    decoded_brand: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    decoded_country: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    #: From the learned VDS map, only when support and purity clear thresholds.
    decoded_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="SET NULL"), nullable=True
    )
    decoded_variant_support: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Whether the decode agreed with the STNK. Disagreement raises a WARNING;
    #: it never changes an STNK value.
    agrees_with_stnk: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True, index=True)
    disagreement_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    check_digit_valid: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    lookup_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)


class VerificationQueueItem(Base, TimestampMixin):
    """Human verification queue for low-confidence extractions (§5.4)."""

    __tablename__ = "verification_queue"

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Which fields fell below their confidence threshold, with the values and
    #: thresholds, so the reviewer sees exactly what to check.
    low_confidence_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    triggered_by: Mapped[str] = mapped_column(sa.String(48), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default=sa.text("100"))
    claimed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    resolution_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
