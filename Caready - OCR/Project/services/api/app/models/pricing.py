"""Historical auction records, OTR price series, anchors, and price results (§8)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import (
    AuctionOutcome,
    DataSufficiencyTier,
    PriceConfidence,
    SellerType,
    TaxStatus,
    Transmission,
)
from app.models.base import Base, TimestampMixin, enum_column, uuid_pk

#: IDR amounts. Numeric, never float - a float rupiah figure accumulates
#: rounding error across aggregations and cannot be reconciled with an
#: accounting system.
Money = sa.Numeric(16, 2)


class AuctionRecord(Base, TimestampMixin):
    """A historical auction outcome. The pricing model's training data.

    UNSOLD UNITS BELONG HERE (§8.3). They are left-censored observations - we
    know true market value was below the reserve, not that the row is missing.
    Training only on sold units biases the model upward and inflates floor
    prices, which is exactly the failure this system exists to prevent.
    """

    __tablename__ = "auction_records"
    __table_args__ = (
        sa.Index("ix_auction_variant_year", "variant_id", "model_year"),
        sa.Index("ix_auction_date_outcome", "auction_date", "outcome"),
        sa.CheckConstraint("model_year BETWEEN 1950 AND 2100", name="model_year_plausible"),
        sa.CheckConstraint(
            "odometer_km IS NULL OR odometer_km BETWEEN 0 AND 1000000", name="odometer_plausible"
        ),
        sa.CheckConstraint(
            "(outcome = 'sold' AND sale_price IS NOT NULL) OR (outcome <> 'sold')",
            name="sold_requires_price",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    #: External reference from the legacy auction system, for reconciliation.
    external_ref: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, unique=True, index=True)
    #: Set when this record originated from a unit priced by this system.
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- vehicle ---
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Raw strings as they appeared in the source system. Retained because the
    #: catalog bootstrap mines these, and because a later catalog correction
    #: must be able to re-resolve historical rows.
    raw_merk: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    raw_tipe: Mapped[str | None] = mapped_column(sa.String(192), nullable=True)
    raw_model: Mapped[str | None] = mapped_column(sa.String(192), nullable=True)
    model_year: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, index=True)
    transmission: Mapped[Transmission | None] = mapped_column(enum_column(Transmission), nullable=True)
    #: Null is meaningful and common in legacy data - it is not imputed to zero.
    odometer_km: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    colour: Mapped[str | None] = mapped_column(sa.String(48), nullable=True)
    engine_cc: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    # --- condition ---
    grade_label: Mapped[str | None] = mapped_column(sa.String(16), nullable=True, index=True)
    damage_score: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    celah_panel_present: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    rust_present: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    repaint_present: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    #: Per-panel-group damage aggregates, as generated for model features.
    damage_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tax_status: Mapped[TaxStatus | None] = mapped_column(enum_column(TaxStatus), nullable=True)

    # --- auction ---
    auction_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    auction_location: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    seller_type: Mapped[SellerType | None] = mapped_column(enum_column(SellerType), nullable=True, index=True)
    outcome: Mapped[AuctionOutcome] = mapped_column(enum_column(AuctionOutcome), nullable=False, index=True)

    #: Null for every unsold row. The censoring bound is `reserve_price`.
    sale_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    reserve_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    #: Present for BELOW_RESERVE, null for NO_BID. The distinction matters -
    #: a no-bid row carries less information and is weighted lower.
    highest_bid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    bidder_count: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)

    #: New-car OTR price for this variant at the auction date, resolved from
    #: the price series. The residual ratio is derived from it.
    otr_price_at_auction: Mapped[Decimal | None] = mapped_column(Money, nullable=True)

    # --- data quality ---
    #: Synthetic seed data is marked so it can never be mistaken for real
    #: history, in the UI, in reports, or in a training run.
    is_synthetic: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), index=True
    )
    #: Set by the deduplication pass. Duplicates are flagged, not deleted -
    #: deleting them destroys the evidence that a duplicate existed.
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("auction_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    excluded_from_training: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), index=True
    )
    exclusion_reason: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    @property
    def is_censored(self) -> bool:
        """Left-censored: true value is below the reserve, by an unknown amount."""
        return self.outcome != AuctionOutcome.SOLD


class OtrPriceSnapshot(Base, TimestampMixin):
    """One ingestion run against one source (§6.2).

    Every fetch is snapshotted. Prices are a time series and a row is never
    overwritten - overwriting would destroy the ability to reconstruct what
    the model saw at training time.
    """

    __tablename__ = "otr_price_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    adapter: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    adapter_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )
    url: Mapped[str | None] = mapped_column(sa.String(1024), nullable=True)
    http_status: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    #: Hash of the fetched payload. An unchanged hash across runs means a
    #: conditional request correctly short-circuited, not that prices froze.
    content_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    row_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    #: Adapter breakage fails loudly. A run yielding zero rows is an alert,
    #: never a silent stale-data condition.
    succeeded: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())


class OtrPrice(Base, TimestampMixin):
    """New-car on-the-road price for a variant at a point in time."""

    __tablename__ = "otr_prices"
    __table_args__ = (
        sa.Index("ix_otr_prices_variant_effective", "variant_id", "effective_date"),
        sa.CheckConstraint("price_idr > 0", name="price_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("otr_price_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Retained even after variant resolution, so a later catalog correction
    #: can re-resolve historical price rows.
    raw_label: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    model_year: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(sa.String(48), nullable=True, index=True)
    price_idr: Mapped[Decimal] = mapped_column(Money, nullable=False)
    effective_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    is_synthetic: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())


class ResidualAnchor(Base, TimestampMixin):
    """Layer 1: realised price as a share of new-car OTR (§8.1).

    Aggregated with shrinkage toward progressively coarser parents when a cell
    is thin. This is what keeps predictions sane for rare models with little
    history, and it is the fallback when the ML model has insufficient support.
    """

    __tablename__ = "residual_anchors"
    __table_args__ = (
        sa.UniqueConstraint("anchor_version", "cell_key", name="uq_residual_anchors_version_cell"),
        sa.CheckConstraint("sample_count >= 0", name="sample_count_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    anchor_version: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    #: Which hierarchy level this row is - e.g. "variant_id:model_year".
    level: Mapped[str] = mapped_column(sa.String(48), nullable=False, index=True)
    #: Canonical key for the cell, e.g. "<uuid>|2019".
    cell_key: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)

    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    vehicle_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("vehicle_models.id", ondelete="CASCADE"), nullable=True, index=True
    )
    model_year: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)
    segment: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    age_years: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)

    #: Shrunk estimate actually used downstream.
    ratio: Mapped[float] = mapped_column(sa.Float, nullable=False)
    #: Unshrunk cell mean, kept for diagnostics - a large gap between the two
    #: is the signal that a cell is being carried by its parent.
    raw_ratio: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    parent_ratio: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    shrinkage_weight: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    sample_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    #: Dispersion within the cell; feeds the band-width sanity check.
    ratio_std: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    is_synthetic: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false())


class PricingModelVersion(Base, TimestampMixin):
    """A trained, MLflow-tracked model artefact."""

    __tablename__ = "pricing_model_versions"
    __table_args__ = (sa.UniqueConstraint("name", "version", name="uq_pricing_model_name_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(sa.String(96), nullable=False, index=True)
    version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    kind: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    mlflow_run_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    mlflow_model_uri: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)

    trained_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    training_rows: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    censored_rows: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Holdout metrics, including the baseline comparison. A LightGBM run that
    #: fails to beat the baseline is recorded as such, not suppressed (§8.2).
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    beats_baseline: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    baseline_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    feature_list: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    anchor_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.false(), index=True)
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    activated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: True when trained on synthetic seed data. Such a model must never be
    #: presented as evidence of pricing accuracy (§0.6).
    trained_on_synthetic: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), index=True
    )


class PriceResult(Base, TimestampMixin):
    """A price computation for one unit (§8.4, §8.5).

    AMP        = P50 prediction, unit in REFERENCE condition
    Base price = P30 prediction, unit in ACTUAL condition
    Deduction  = AMP - base price, a DERIVED display value

    The deduction is not a table lookup applied on top of a prediction. Damage
    and grade are already model features; we predict twice and show the
    difference. That keeps the number explainable without being arbitrary.
    """

    __tablename__ = "price_results"
    __table_args__ = (
        sa.Index("ix_price_results_unit_created", "unit_id", "created_at"),
        sa.CheckConstraint("amp_idr >= 0 AND base_price_idr >= 0", name="prices_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("pricing_model_versions.id", ondelete="SET NULL"), nullable=True
    )

    # --- outputs ---
    amp_idr: Mapped[Decimal] = mapped_column(Money, nullable=False)
    base_price_idr: Mapped[Decimal] = mapped_column(Money, nullable=False)
    #: Derived: amp - base_price. Stored so the displayed figure is reproducible.
    deduction_idr: Mapped[Decimal] = mapped_column(Money, nullable=False)
    p30_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    p50_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    p70_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    #: From the auxiliary P(sells | price, features) classifier (§8.3).
    sell_probability: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    # --- provenance and confidence ---
    data_sufficiency_tier: Mapped[DataSufficiencyTier] = mapped_column(
        enum_column(DataSufficiencyTier), nullable=False, index=True
    )
    comparable_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("0"))
    confidence: Mapped[PriceConfidence] = mapped_column(
        enum_column(PriceConfidence), nullable=False, index=True
    )
    #: Every condition that knocked confidence down, so an approver sees
    #: exactly why it is what it is.
    confidence_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    #: Top SHAP feature contributions.
    explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: The historical units used as comparables, including unsold ones -
    #: showing only sold comparables flatters the price.
    comparables: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    #: Feature vector as fed to the model. Makes a past price reproducible.
    feature_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    #: True when the cold-start deduction table was used instead of the
    #: model-difference method. Surfaced in the UI (§8.4).
    coldstart_deduction_used: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), index=True
    )
    coldstart_table_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    pricing_config_version: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    anchor_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    grade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("grades.id", ondelete="SET NULL"), nullable=True
    )

    #: Guard-rail violations that blocked auto-progression.
    guard_rail_violations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    #: Marks output derived from synthetic training data (§0.6, §9).
    is_synthetic_model: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false(), index=True
    )

    # --- human override ---
    override_base_price_idr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    override_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    override_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    superseded_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)

    @property
    def effective_base_price(self) -> Decimal:
        return self.override_base_price_idr if self.override_base_price_idr is not None else self.base_price_idr
