"""SQLAlchemy models.

Every model must be imported here. Alembic's autogenerate compares
`Base.metadata` against the live database, so a model that is never imported
is invisible to migrations and silently drifts.

CI enforces this with `alembic check`, which fails when metadata and the
migrated schema disagree.
"""

from app.models.audit import (
    APPEND_ONLY_TABLES,
    AuditLog,
    JobRun,
    PiiAccessLog,
    UnitStatusTransition,
)
from app.models.base import Base
from app.models.catalog import (
    Brand,
    CatalogCuration,
    Generation,
    Variant,
    VariantAlias,
    VariantResolutionQueueItem,
    VdsVariantMap,
    VehicleModel,
)
from app.models.damage import (
    DamageCorrection,
    DamageDetection,
    Grade,
    VisionInference,
)
from app.models.ocr import (
    CrossCheckResult,
    OcrExtraction,
    PlateConditionAssessment,
    VerificationQueueItem,
    VinDecodeResult,
)
from app.models.photo import Photo, PhotoUploadSession
from app.models.pricing import (
    AuctionRecord,
    OtrPrice,
    OtrPriceSnapshot,
    PriceResult,
    PricingModelVersion,
    ResidualAnchor,
)
from app.models.unit import NonVisualChecklistItem, Unit, UnitStnkData
from app.models.user import RefreshToken, User

__all__ = [
    "APPEND_ONLY_TABLES",
    "AuctionRecord",
    "AuditLog",
    "Base",
    "Brand",
    "CatalogCuration",
    "CrossCheckResult",
    "DamageCorrection",
    "DamageDetection",
    "Generation",
    "Grade",
    "JobRun",
    "NonVisualChecklistItem",
    "OcrExtraction",
    "OtrPrice",
    "OtrPriceSnapshot",
    "Photo",
    "PhotoUploadSession",
    "PiiAccessLog",
    "PlateConditionAssessment",
    "PriceResult",
    "PricingModelVersion",
    "RefreshToken",
    "ResidualAnchor",
    "Unit",
    "UnitStatusTransition",
    "UnitStnkData",
    "User",
    "Variant",
    "VariantAlias",
    "VariantResolutionQueueItem",
    "VdsVariantMap",
    "VehicleModel",
    "VerificationQueueItem",
    "VinDecodeResult",
    "VisionInference",
]
