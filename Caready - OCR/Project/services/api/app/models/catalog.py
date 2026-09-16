"""Vehicle variant catalog (§6.1).

Brand -> Model -> Generation -> Variant -> Transmission / Body / Engine.

This module is deliberately first-class rather than a lookup table bolted onto
`units`. Unresolved variants are the largest source of systematic pricing
error in the system, so variant identity carries its own provenance, its own
alias-learning table, and its own curation surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import BodyType, FuelType, Transmission, VariantResolutionMethod
from app.models.base import Base, TimestampMixin, enum_column, uuid_pk


class Brand(Base, TimestampMixin):
    __tablename__ = "brands"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    #: Uppercased, punctuation-stripped form used for matching.
    normalized_name: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    country: Mapped[str | None] = mapped_column(sa.String(2), nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())

    models: Mapped[list["VehicleModel"]] = relationship(back_populates="brand")


class VehicleModel(Base, TimestampMixin):
    """Named `VehicleModel` rather than `Model` to avoid colliding with the ML
    sense of the word throughout the codebase."""

    __tablename__ = "vehicle_models"
    __table_args__ = (sa.UniqueConstraint("brand_id", "normalized_name", name="uq_vehicle_models_brand_norm"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    normalized_name: Mapped[str] = mapped_column(sa.String(96), nullable=False, index=True)
    #: Coarse market segment - used as a shrinkage parent for the residual
    #: value anchor when a model has too little history of its own (§8.1).
    segment: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())

    brand: Mapped[Brand] = relationship(back_populates="models")
    generations: Mapped[list["Generation"]] = relationship(back_populates="vehicle_model")


class Generation(Base, TimestampMixin):
    __tablename__ = "generations"

    id: Mapped[uuid.UUID] = uuid_pk()
    vehicle_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("vehicle_models.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    year_start: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)
    #: Null means "current generation, still in production".
    year_end: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    facelift_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("generations.id", ondelete="SET NULL"), nullable=True
    )

    vehicle_model: Mapped[VehicleModel] = relationship(back_populates="generations")
    variants: Mapped[list["Variant"]] = relationship(back_populates="generation")

    __table_args__ = (
        sa.CheckConstraint("year_end IS NULL OR year_end >= year_start", name="year_range_valid"),
    )


class Variant(Base, TimestampMixin):
    """A specific sellable configuration.

    Transmission is part of variant identity because the STNK does not record
    it and it moves price materially - so it must be resolved explicitly, not
    inferred.
    """

    __tablename__ = "variants"
    __table_args__ = (
        sa.UniqueConstraint(
            "generation_id", "normalized_trim", "transmission", name="uq_variants_gen_trim_trans"
        ),
        sa.CheckConstraint("engine_cc IS NULL OR engine_cc BETWEEN 400 AND 9000", name="engine_cc_plausible"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("generations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    trim: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    normalized_trim: Mapped[str] = mapped_column(sa.String(96), nullable=False, index=True)
    transmission: Mapped[Transmission] = mapped_column(
        enum_column(Transmission), nullable=False, server_default=Transmission.UNKNOWN.value, index=True
    )
    body_type: Mapped[BodyType] = mapped_column(
        enum_column(BodyType), nullable=False, server_default=BodyType.UNKNOWN.value, index=True
    )
    fuel_type: Mapped[FuelType] = mapped_column(
        enum_column(FuelType), nullable=False, server_default=FuelType.UNKNOWN.value
    )
    engine_cc: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    seats: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    #: Set when an admin merges two catalog entries. The loser keeps a pointer
    #: so historical rows referencing it still resolve, rather than being
    #: rewritten - rewriting history would break reproducibility of past prices.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    generation: Mapped[Generation] = relationship(back_populates="variants")
    aliases: Mapped[list["VariantAlias"]] = relationship(back_populates="variant")

    @property
    def is_merged(self) -> bool:
        return self.merged_into_id is not None


class VariantAlias(Base, TimestampMixin):
    """Learned mapping from raw STNK strings to a catalog variant (§6.1).

    Every manual resolution by an appraiser writes or increments a row here.
    Once `support_count` clears the configured threshold the alias becomes
    trusted for auto-accept. Conflicting resolutions quarantine the alias for
    admin attention rather than being majority-voted.
    """

    __tablename__ = "variant_aliases"
    __table_args__ = (
        sa.UniqueConstraint("raw_key", name="uq_variant_aliases_raw_key"),
        sa.CheckConstraint("support_count >= 0", name="support_count_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: Normalised concatenation of merk|tipe|model - the matcher's lookup key.
    raw_key: Mapped[str] = mapped_column(sa.String(384), nullable=False, index=True)
    raw_merk: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    raw_tipe: Mapped[str | None] = mapped_column(sa.String(192), nullable=True)
    raw_model: Mapped[str | None] = mapped_column(sa.String(192), nullable=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    support_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("1"))
    #: Share of supporting resolutions that agreed on this variant.
    purity: Mapped[float] = mapped_column(sa.Float, nullable=False, server_default=sa.text("1.0"))
    #: Set when resolutions disagree. A quarantined alias is never auto-applied.
    quarantined: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false(), index=True)
    quarantine_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False, server_default="manual_resolution")
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    variant: Mapped[Variant] = relationship(back_populates="aliases")


class VdsVariantMap(Base, TimestampMixin):
    """Empirically learned VIN VDS-prefix to variant mapping (§5.3).

    Built from Caready's own historical data - specifically from units whose
    variant was resolved by a human - never from an assumption about what the
    manufacturer encodes where. Applied only above the support and purity
    thresholds in config/crosschecks.yaml, and only ever to raise a
    disagreement flag against the STNK, never to overwrite it.
    """

    __tablename__ = "vds_variant_map"
    __table_args__ = (sa.UniqueConstraint("wmi", "vds_prefix", name="uq_vds_variant_map_wmi_prefix"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    wmi: Mapped[str] = mapped_column(sa.String(3), nullable=False, index=True)
    vds_prefix: Mapped[str] = mapped_column(sa.String(6), nullable=False, index=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    support_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    purity: Mapped[float] = mapped_column(sa.Float, nullable=False, server_default=sa.text("0.0"))
    #: Snapshot of the competing variants and their counts, for audit.
    distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rebuilt_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


class CatalogCuration(Base, TimestampMixin):
    """Append-only record of admin catalog edits.

    Every merge, alias, and correction is recorded so the matcher's behaviour
    over time is explainable, and so a bad bulk edit can be identified and
    reversed by a human.
    """

    __tablename__ = "catalog_curations"

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class VariantResolutionQueueItem(Base, TimestampMixin):
    """A unit awaiting mandatory manual variant selection (§6.1 step 3).

    Pricing does not run while an item sits here. This is stricter than
    degrading confidence, and deliberately so: a price computed on a guessed
    variant looks authoritative and is directionally wrong.
    """

    __tablename__ = "variant_resolution_queue"

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    #: Ranked candidate variants with their match scores, shown to the appraiser.
    suggestions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    best_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    reason: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="SET NULL"), nullable=True
    )
    resolution_method: Mapped[VariantResolutionMethod | None] = mapped_column(
        enum_column(VariantResolutionMethod), nullable=True
    )
