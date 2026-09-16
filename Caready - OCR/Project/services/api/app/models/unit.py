"""Units, STNK data, and the non-visual checklist."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import (
    ChecklistAnswer,
    NonVisualCheckItem,
    SellerType,
    TaxStatus,
    UnitStatus,
    VariantResolutionMethod,
)
from app.models.base import Base, EncryptedText, TimestampMixin, enum_column, uuid_pk


class Unit(Base, TimestampMixin):
    """One vehicle passing through inspection and pricing."""

    __tablename__ = "units"
    __table_args__ = (
        sa.Index("ix_units_status_created", "status", "created_at"),
        sa.CheckConstraint(
            "odometer_km IS NULL OR odometer_km BETWEEN 0 AND 1000000", name="odometer_plausible"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Human-facing reference, e.g. CR-2026-000412. Stable and never reused.
    code: Mapped[str] = mapped_column(sa.String(32), nullable=False, unique=True, index=True)
    status: Mapped[UnitStatus] = mapped_column(
        enum_column(UnitStatus), nullable=False, server_default=UnitStatus.DRAFT.value, index=True
    )

    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch_code: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)

    # --- draft / offline reconciliation (§4.3) ---
    #: Client-generated id for the offline draft. The uniqueness constraint is
    #: what makes "syncs without duplicates" hold even if the PWA retries a
    #: unit-creation request it never saw a response to.
    client_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, unique=True, index=True
    )
    #: True until all four intake captures have synced.
    intake_complete: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())

    # --- variant resolution (§6.1) ---
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    variant_resolution_method: Mapped[VariantResolutionMethod] = mapped_column(
        enum_column(VariantResolutionMethod),
        nullable=False,
        server_default=VariantResolutionMethod.UNRESOLVED.value,
        index=True,
    )
    variant_match_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    variant_resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    variant_resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    # --- denormalised pricing inputs ---
    # Copied from the STNK extraction after verification so the pricing
    # pipeline does not reach into an encrypted PII table for every read.
    model_year: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True, index=True)
    odometer_km: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    colour: Mapped[str | None] = mapped_column(sa.String(48), nullable=True)
    tax_status: Mapped[TaxStatus] = mapped_column(
        enum_column(TaxStatus), nullable=False, server_default=TaxStatus.UNKNOWN.value, index=True
    )
    tax_valid_until: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    seller_type: Mapped[SellerType | None] = mapped_column(enum_column(SellerType), nullable=True, index=True)

    # --- workflow ---
    #: Cached rollup of BLOCKER-severity checks. The authoritative list lives
    #: in cross_check_results; this exists so the unit list can filter without
    #: a join, and is recomputed whenever a check is written.
    has_blocking_flags: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), index=True
    )
    blocking_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    terminal_status_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True, index=True
    )
    #: Suppresses the PDP retention purge for this unit.
    legal_hold: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())

    stnk: Mapped["UnitStnkData | None"] = relationship(
        back_populates="unit", uselist=False, cascade="all, delete-orphan"
    )
    checklist_items: Mapped[list["NonVisualChecklistItem"]] = relationship(
        back_populates="unit", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Unit {self.code} status={self.status}>"


class UnitStnkData(Base, TimestampMixin):
    """STNK fields extracted by ICR (§5.2).

    The STNK is the AUTHORITATIVE source for brand / type / model / year. VIN
    decoding is an optional cross-check that may flag a disagreement but never
    overwrites anything here (§5.3).

    PII columns are encrypted at rest and masked by default in every view.
    See config/pdp.yaml for the field-level classification.
    """

    __tablename__ = "unit_stnk_data"

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # --- identity ---
    #: Not encrypted: it is the primary operational lookup key and an
    #: encrypted column cannot be indexed. Protected by masking plus access
    #: logging instead - see config/pdp.yaml.
    nomor_registrasi: Mapped[str | None] = mapped_column(sa.String(24), nullable=True, index=True)

    # --- PII (encrypted, masked by default) ---
    nama_pemilik: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    alamat: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    #: Not always present on an STNK. When absent it is not inferred.
    nik: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    nomor_bpkb: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)

    # --- vehicle description (authoritative) ---
    merk: Mapped[str | None] = mapped_column(sa.String(96), nullable=True, index=True)
    tipe: Mapped[str | None] = mapped_column(sa.String(192), nullable=True, index=True)
    jenis: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    model: Mapped[str | None] = mapped_column(sa.String(192), nullable=True, index=True)
    tahun_pembuatan: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True, index=True)
    isi_silinder: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    nomor_rangka: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    nomor_mesin: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    warna: Mapped[str | None] = mapped_column(sa.String(48), nullable=True)
    bahan_bakar: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    warna_tnkb: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    tahun_registrasi: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    kode_lokasi: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    # --- tax panel ---
    berlaku_sampai: Mapped[date | None] = mapped_column(sa.Date, nullable=True, index=True)
    tanggal_pajak: Mapped[date | None] = mapped_column(sa.Date, nullable=True)

    # --- provenance ---
    #: Per-field confidence from the OCR provider, keyed by field name. Drives
    #: the human verification routing in config/crosschecks.yaml.
    field_confidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Which fields a human has since corrected, and to what.
    verified_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Set by the retention purge job when PII columns are cleared.
    pii_purged_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)

    unit: Mapped[Unit] = relationship(back_populates="stnk")


class NonVisualChecklistItem(Base, TimestampMixin):
    """Mandatory inspector checklist for conditions AI cannot see (§8.4).

    Exterior-only grading cannot detect flood damage, chassis repair, engine or
    transmission condition, or odometer tampering. Without this gate,
    mechanically damaged units are systematically overpriced.

    A FLAGGED item blocks auto-approval and requires appraiser action. Whether
    this checklist is accepted as mandatory, and its exact item list, is
    OPEN_ITEMS.md #6.
    """

    __tablename__ = "non_visual_checklist_items"
    __table_args__ = (sa.UniqueConstraint("unit_id", "item", name="uq_non_visual_unit_item"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item: Mapped[NonVisualCheckItem] = mapped_column(enum_column(NonVisualCheckItem), nullable=False)
    answer: Mapped[ChecklistAnswer] = mapped_column(
        enum_column(ChecklistAnswer), nullable=False, server_default=ChecklistAnswer.NOT_CHECKED.value, index=True
    )
    #: Required when `answer` is FLAGGED - enforced in the service layer so the
    #: message can be specific, and re-asserted by a CHECK constraint.
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    answered_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    unit: Mapped[Unit] = relationship(back_populates="checklist_items")
