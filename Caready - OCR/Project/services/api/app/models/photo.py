"""Photo storage metadata (§4.2).

Photos themselves live in object storage. This table holds provenance,
integrity, and quality metadata - everything needed to decide whether a photo
can be trusted, without fetching the bytes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import CaptureType
from app.models.base import Base, TimestampMixin, enum_column, uuid_pk


class Photo(Base, TimestampMixin):
    __tablename__ = "photos"
    __table_args__ = (
        # Idempotency for the offline sync path (§4.3). A retried upload with
        # the same client key is a no-op rather than a duplicate row - this is
        # what makes the M1 acceptance criterion hold.
        sa.UniqueConstraint("idempotency_key", name="uq_photos_idempotency_key"),
        sa.Index("ix_photos_unit_capture", "unit_id", "capture_type"),
        # Perceptual-hash lookups scan this index for reuse detection.
        sa.Index("ix_photos_phash", "phash"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capture_type: Mapped[CaptureType] = mapped_column(enum_column(CaptureType), nullable=False, index=True)
    #: Ordinal within a repeatable capture type (damage close-ups). 0 for the
    #: single-slot captures.
    sequence: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, server_default=sa.text("0"))

    # --- object storage ---
    #: The original is immutable. It is never overwritten or re-encoded.
    s3_key_original: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    s3_key_derivative: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    content_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, server_default="image/jpeg")
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    width_px: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: sha256 of the original bytes. Integrity, and exact-duplicate detection.
    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)

    # --- provenance: server-stamped, never client-supplied (§4.2) ---
    captured_at_server: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    device_fingerprint: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    client_ip: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    gps_lon: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    gps_accuracy_m: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    # --- client-reported, stored for comparison but NOT trusted ---
    #: The device clock is trivially changed. Kept because a large divergence
    #: from `captured_at_server` is itself a signal worth flagging.
    client_captured_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Original EXIF stored verbatim and separately. The derivative is stripped.
    exif: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- integrity ---
    #: Perceptual hash for reuse detection across units (§5.4).
    phash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    #: Set when a collision is found. The matched photo is recorded so a human
    #: can compare the two images side by side.
    phash_collision_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="SET NULL"), nullable=True
    )
    phash_collision_distance: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)

    # --- quality gate (§4.2) ---
    #: Metrics computed server-side. The client gate is a UX affordance; this
    #: is the enforcement record.
    quality_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality_passed: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True, index=True)
    quality_failures: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    #: Set when an inspector overrode a repeated quality rejection. Requires a
    #: typed reason and flags the photo for appraiser review.
    quality_override_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # --- offline sync (§4.3) ---
    idempotency_key: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: How long the capture sat in the offline queue before syncing. Useful
    #: operationally; also a weak signal when unusually long.
    queued_seconds: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: Set by the PDP retention purge for document captures.
    purged_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True, index=True)

    ocr_extractions: Mapped[list["OcrExtraction"]] = relationship(  # noqa: F821
        back_populates="photo", cascade="all, delete-orphan"
    )


class PhotoUploadSession(Base, TimestampMixin):
    """Resumable chunked upload state (§4.3).

    Yard networks drop mid-upload. Rather than restart a 6MB photo from zero,
    the client uploads in chunks against a session and resumes from the last
    acknowledged offset.
    """

    __tablename__ = "photo_upload_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: Present before the unit exists server-side - the draft is created from
    #: the client's offline id once captures 1 and 2 arrive.
    client_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    capture_type: Mapped[CaptureType] = mapped_column(enum_column(CaptureType), nullable=False)
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    total_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    received_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, server_default=sa.text("0"))
    #: Multipart upload id from the object store.
    upload_id: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    s3_key: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    parts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Abandoned sessions are swept so incomplete multipart uploads do not
    #: accumulate storage cost.
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("photos.id", ondelete="SET NULL"), nullable=True
    )
