"""Exterior damage detections, the label store, and grades (§7)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import (
    CorrectionAction,
    DamageType,
    DetectionSource,
    GradeSource,
    Panel,
    PanelGroup,
    VisionProviderName,
)
from app.models.base import Base, TimestampMixin, enum_column, uuid_pk


class VisionInference(Base, TimestampMixin):
    """One vision provider call against one exterior photo.

    Model version and prompt hash are recorded so that a grade can be
    reproduced exactly, and so a prompt change shows up as a discontinuity in
    the data rather than as unexplained drift.
    """

    __tablename__ = "vision_inferences"

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[VisionProviderName] = mapped_column(enum_column(VisionProviderName), nullable=False)
    model_version: Mapped[str] = mapped_column(sa.String(96), nullable=False, index=True)
    #: sha256 of the prompt text. A prompt edit is a model change.
    prompt_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    schema_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Schema validation is strict. A response that fails is rejected, never
    #: partially coerced - a half-parsed detection set silently understates
    #: damage, which biases price upward.
    schema_valid: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    schema_errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    succeeded: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    detections: Mapped[list["DamageDetection"]] = relationship(back_populates="inference")


class DamageDetection(Base, TimestampMixin):
    """A single damage observation (§7.2).

    Produced by the vision provider, by the inspector marking damage during
    capture, or added by an appraiser during review. `source` distinguishes
    them, and AI rows are never mutated in place - a correction creates a
    DamageCorrection and supersedes the original.
    """

    __tablename__ = "damage_detections"
    __table_args__ = (
        sa.Index("ix_damage_unit_panel", "unit_id", "panel"),
        sa.Index("ix_damage_unit_active", "unit_id", "superseded_at"),
        sa.CheckConstraint("severity BETWEEN 1 AND 3", name="severity_in_range"),
        sa.CheckConstraint("confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_in_range"),
        sa.CheckConstraint(
            "area_ratio IS NULL OR area_ratio BETWEEN 0 AND 1", name="area_ratio_in_range"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    inference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("vision_inferences.id", ondelete="SET NULL"), nullable=True
    )

    panel: Mapped[Panel] = mapped_column(enum_column(Panel), nullable=False, index=True)
    #: Denormalised from the panel, for pricing feature generation (§8.1).
    panel_group: Mapped[PanelGroup] = mapped_column(enum_column(PanelGroup), nullable=False, index=True)
    damage_type: Mapped[DamageType] = mapped_column(enum_column(DamageType), nullable=False, index=True)
    #: 1 minor (polish), 2 moderate (panel work), 3 severe (replacement).
    severity: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)

    #: [x, y, w, h] normalised to the source photo.
    bbox: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    #: Detection area as a fraction of the panel area; feeds the grading
    #: area multiplier.
    area_ratio: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(sa.Float, nullable=True, index=True)

    source: Mapped[DetectionSource] = mapped_column(enum_column(DetectionSource), nullable=False, index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: Set when a correction replaces this detection. AI output is immutable;
    #: the original always remains readable alongside the correction.
    superseded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("damage_detections.id", ondelete="SET NULL"), nullable=True
    )
    #: Excluded from scoring for being below the confidence floor. Counted and
    #: shown in the UI rather than silently dropped.
    excluded_low_confidence: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )

    inference: Mapped[VisionInference | None] = relationship(back_populates="detections")

    @property
    def is_active(self) -> bool:
        return self.superseded_at is None


class DamageCorrection(Base, TimestampMixin):
    """Appraiser correction to an AI detection - the Stage 2 label store (§7.3).

    This table is the deliberate data flywheel. After roughly 3-6 months of
    corrections it becomes the training set for a supervised detector that
    replaces the cold-start VLM.

    Deletions are kept as hard negatives; confirmations as positives. Both are
    valuable training signal and neither is discarded.
    """

    __tablename__ = "damage_corrections"
    __table_args__ = (sa.Index("ix_damage_corrections_export", "exported_at", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Null for ADD - there was no original detection.
    detection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("damage_detections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[CorrectionAction] = mapped_column(enum_column(CorrectionAction), nullable=False, index=True)

    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    corrected_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: Model version being corrected. Lets us measure whether a new provider
    #: version actually reduced the correction rate.
    ai_model_version: Mapped[str | None] = mapped_column(sa.String(96), nullable=True, index=True)

    #: Set when included in a training-set export.
    exported_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    export_batch: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)


class Grade(Base, TimestampMixin):
    """A computed or final exterior grade (§7.4).

    Both the AI grade and the final grade are stored as separate rows. The AI
    value is never overwritten - an override creates a new row with
    `source=FINAL` and a mandatory reason.
    """

    __tablename__ = "grades"
    __table_args__ = (
        sa.Index("ix_grades_unit_source", "unit_id", "source"),
        sa.CheckConstraint("damage_score >= 0", name="damage_score_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[GradeSource] = mapped_column(enum_column(GradeSource), nullable=False, index=True)

    grade_label: Mapped[str] = mapped_column(sa.String(16), nullable=False, index=True)
    damage_score: Mapped[float] = mapped_column(sa.Float, nullable=False)
    #: Band the raw score landed in, before downgrade rules.
    pre_downgrade_label: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    #: Which downgrade rules fired, by id. Shown in the UI so an appraiser can
    #: always see why a grade was capped.
    applied_downgrade_rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    #: Per-detection point attribution. Every point in the score is traceable
    #: to one detection.
    score_breakdown: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: Version of config/grading.yaml used. Required for reproducibility.
    rubric_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    #: True while the rubric is the documented placeholder rather than
    #: Caready's real scale. Drives a UI warning and a pricing-confidence
    #: degradation. See docs/OPEN_ITEMS.md #1.
    rubric_placeholder: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())

    #: Set when the photo set was incomplete or a panel group was unassessed.
    provisional: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false(), index=True)
    provisional_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # --- override (source=FINAL only) ---
    overrides_grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("grades.id", ondelete="SET NULL"), nullable=True
    )
    #: Mandatory when this row overrides an AI grade.
    override_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: Only one active grade per source per unit; superseded rows are retained.
    superseded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
