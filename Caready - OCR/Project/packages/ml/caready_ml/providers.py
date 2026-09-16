"""Pluggable provider interfaces (§5.1, §7.3).

These Protocols are the swap points that make the vision and OCR strategies
replaceable without touching business logic:

  * OCR: a cloud document-AI adapter and a local PaddleOCR adapter ship at M2.
    The local one keeps STNK images on our infrastructure, which is the
    PDP-preferred posture.

  * Vision: Stage 1 is a vision-language model behind `VisionProvider`, because
    there is no labelled data yet. Stage 2 is a supervised detector trained on
    the appraiser-correction label store. Only the implementation changes.

Defined here rather than in the API service so the worker, the training code,
and the tests all depend on one definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class FieldValue:
    """One extracted field with its own confidence.

    Per-field confidence is required (§5.1): a document-level score cannot
    distinguish a crisp VIN on a glared document from a guessed one, and the
    verification routing in config/crosschecks.yaml is per-field.
    """

    value: str | int | date | None
    confidence: float
    #: Where on the page the value was read from, when the provider reports it.
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class ExtractionResult:
    fields: dict[str, FieldValue]
    #: Unmodified provider payload. Persisted verbatim - when a field is
    #: disputed months later this is what settles it.
    raw_response: dict[str, Any]
    provider: str
    provider_version: str
    duration_ms: int | None = None
    #: True when the image was redacted before an external call (§10).
    pii_redacted: bool = False

    def confidence_of(self, name: str) -> float:
        fv = self.fields.get(name)
        return fv.confidence if fv else 0.0

    def value_of(self, name: str) -> Any:
        fv = self.fields.get(name)
        return fv.value if fv else None


@dataclass(frozen=True)
class PlateConditionResult:
    classification: str
    confidence: float
    #: A classification without a reason is not actionable for an appraiser.
    rationale: str | None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Detection:
    panel: str
    damage_type: str
    severity: int
    #: [x, y, w, h], normalised to the source image.
    bbox: list[float] | None
    area_ratio: float | None
    confidence: float


@dataclass(frozen=True)
class VisionResult:
    detections: list[Detection]
    raw_response: dict[str, Any]
    provider: str
    model_version: str
    #: sha256 of the prompt. A prompt edit is a model change, and must show up
    #: as a discontinuity in the data rather than as unexplained drift.
    prompt_hash: str | None = None
    schema_version: str | None = None
    schema_valid: bool = True
    schema_errors: list[str] = field(default_factory=list)
    duration_ms: int | None = None


@runtime_checkable
class OcrProvider(Protocol):
    """§5.1. Implementations: `stub`, `paddle`, `cloud_docai`."""

    name: str
    version: str

    def extract_stnk(self, image: bytes) -> ExtractionResult: ...

    def extract_vin_plate(self, image: bytes) -> ExtractionResult: ...

    def extract_odometer(self, image: bytes) -> ExtractionResult: ...

    def extract_engine_no(self, image: bytes) -> ExtractionResult: ...

    def classify_plate_condition(self, image: bytes) -> PlateConditionResult: ...


@runtime_checkable
class VisionProvider(Protocol):
    """§7.3. Implementations: `stub`, `vlm` (Stage 1), `yolo` (Stage 2)."""

    name: str
    version: str

    def detect_damage(self, image: bytes, *, capture_type: str) -> VisionResult: ...


@runtime_checkable
class PriceSourceAdapter(Protocol):
    """§6.2. New-car OTR price ingestion.

    CSV import is the guaranteed fallback and the CI default. Web adapters are
    opt-in per environment - see docs/OPEN_ITEMS.md #3 on the legal position.
    """

    name: str
    version: str

    def fetch(self) -> list[dict[str, Any]]: ...
