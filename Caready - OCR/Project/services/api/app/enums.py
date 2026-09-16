"""Shared vocabulary for the Caready system.

This module is the single source of truth for every enumerated value that
crosses a module boundary (DB, API, worker, ML, seed generators, config files).

Rule: if a string appears in both a YAML config file and the database, its
canonical spelling is defined here. Config loaders validate against these.
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """str-valued enum; serialises as its value in JSON and SQL."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def values(cls) -> list[str]:
        return [m.value for m in cls]


# --------------------------------------------------------------------------
# Identity and access
# --------------------------------------------------------------------------


class Role(StrEnum):
    """RBAC roles. See docs/ARCHITECTURE.md §Roles.

    Ordering is NOT a hierarchy: `approver` is a superset of `appraiser`, but
    `admin` is an orthogonal operational role. Permission checks are explicit
    per-capability, never `role >= X`.
    """

    INSPECTOR = "inspector"
    APPRAISER = "appraiser"
    APPROVER = "approver"
    ADMIN = "admin"


class Capability(StrEnum):
    """Server-side capabilities. UI hiding is not a permission model."""

    UNIT_CREATE = "unit:create"
    UNIT_CAPTURE = "unit:capture"
    UNIT_SUBMIT = "unit:submit"
    UNIT_READ = "unit:read"
    UNIT_READ_PRICE = "unit:read_price"
    UNIT_OVERRIDE_GRADE = "unit:override_grade"
    UNIT_OVERRIDE_DAMAGE = "unit:override_damage"
    UNIT_RESOLVE_VARIANT = "unit:resolve_variant"
    UNIT_APPROVE = "unit:approve"
    PII_UNMASK = "pii:unmask"
    CATALOG_CURATE = "catalog:curate"
    CONFIG_WRITE = "config:write"
    USER_MANAGE = "user:manage"
    MODEL_DEPLOY = "model:deploy"


#: Explicit capability grants. Inspectors deliberately cannot read prices -
#: see docs/ARCHITECTURE.md §Roles for the rationale (removes the incentive to
#: shade damage reporting toward a target price).
ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.INSPECTOR: frozenset(
        {
            Capability.UNIT_CREATE,
            Capability.UNIT_CAPTURE,
            Capability.UNIT_SUBMIT,
            Capability.UNIT_READ,
        }
    ),
    Role.APPRAISER: frozenset(
        {
            Capability.UNIT_READ,
            Capability.UNIT_READ_PRICE,
            Capability.UNIT_OVERRIDE_GRADE,
            Capability.UNIT_OVERRIDE_DAMAGE,
            Capability.UNIT_RESOLVE_VARIANT,
            Capability.PII_UNMASK,
        }
    ),
    Role.APPROVER: frozenset(
        {
            Capability.UNIT_READ,
            Capability.UNIT_READ_PRICE,
            Capability.UNIT_OVERRIDE_GRADE,
            Capability.UNIT_OVERRIDE_DAMAGE,
            Capability.UNIT_RESOLVE_VARIANT,
            Capability.UNIT_APPROVE,
            Capability.PII_UNMASK,
        }
    ),
    Role.ADMIN: frozenset(
        {
            Capability.UNIT_READ,
            Capability.CATALOG_CURATE,
            Capability.CONFIG_WRITE,
            Capability.USER_MANAGE,
            Capability.MODEL_DEPLOY,
            Capability.PII_UNMASK,
        }
    ),
}


# --------------------------------------------------------------------------
# Unit lifecycle
# --------------------------------------------------------------------------


class UnitStatus(StrEnum):
    DRAFT = "DRAFT"
    ICR_DONE = "ICR_DONE"
    GRADED = "GRADED"
    PRICED = "PRICED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


#: Legal forward transitions. Enforced by the state machine in M7; declared
#: here at M0 so the audit log and seed data agree on what is reachable.
UNIT_TRANSITIONS: dict[UnitStatus, frozenset[UnitStatus]] = {
    UnitStatus.DRAFT: frozenset({UnitStatus.ICR_DONE, UnitStatus.REJECTED}),
    UnitStatus.ICR_DONE: frozenset({UnitStatus.GRADED, UnitStatus.REJECTED}),
    UnitStatus.GRADED: frozenset({UnitStatus.PRICED, UnitStatus.REJECTED}),
    UnitStatus.PRICED: frozenset({UnitStatus.PENDING_APPROVAL, UnitStatus.REJECTED}),
    UnitStatus.PENDING_APPROVAL: frozenset({UnitStatus.APPROVED, UnitStatus.REJECTED}),
    UnitStatus.APPROVED: frozenset(),
    UnitStatus.REJECTED: frozenset({UnitStatus.DRAFT}),
}


# --------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------


class CaptureType(StrEnum):
    """Photo capture slots.

    INTAKE_* are the four mandatory intake captures (§4.1).
    EXT_* are the nine mandatory exterior angles (§7.1).
    DAMAGE_CLOSEUP is repeatable, one per inspector-marked damage.
    """

    INTAKE_VIN_PLATE = "INTAKE_VIN_PLATE"
    INTAKE_STNK_FRONT = "INTAKE_STNK_FRONT"
    INTAKE_ODOMETER = "INTAKE_ODOMETER"
    INTAKE_ENGINE_NO = "INTAKE_ENGINE_NO"

    EXT_FRONT = "EXT_FRONT"
    EXT_FRONT_34_LEFT = "EXT_FRONT_34_LEFT"
    EXT_LEFT = "EXT_LEFT"
    EXT_REAR_34_LEFT = "EXT_REAR_34_LEFT"
    EXT_REAR = "EXT_REAR"
    EXT_REAR_34_RIGHT = "EXT_REAR_34_RIGHT"
    EXT_RIGHT = "EXT_RIGHT"
    EXT_FRONT_34_RIGHT = "EXT_FRONT_34_RIGHT"
    EXT_ROOF = "EXT_ROOF"

    DAMAGE_CLOSEUP = "DAMAGE_CLOSEUP"


#: The four intake captures. A unit is not created server-side until at least
#: INTAKE_VIN_PLATE and INTAKE_STNK_FRONT have synced (§4.3).
INTAKE_CAPTURES: tuple[CaptureType, ...] = (
    CaptureType.INTAKE_VIN_PLATE,
    CaptureType.INTAKE_STNK_FRONT,
    CaptureType.INTAKE_ODOMETER,
    CaptureType.INTAKE_ENGINE_NO,
)

INTAKE_CAPTURES_REQUIRED_FOR_UNIT_CREATION: tuple[CaptureType, ...] = (
    CaptureType.INTAKE_VIN_PLATE,
    CaptureType.INTAKE_STNK_FRONT,
)

#: The nine mandatory exterior angles. The set is rejected if any is missing.
EXTERIOR_CAPTURES: tuple[CaptureType, ...] = (
    CaptureType.EXT_FRONT,
    CaptureType.EXT_FRONT_34_LEFT,
    CaptureType.EXT_LEFT,
    CaptureType.EXT_REAR_34_LEFT,
    CaptureType.EXT_REAR,
    CaptureType.EXT_REAR_34_RIGHT,
    CaptureType.EXT_RIGHT,
    CaptureType.EXT_FRONT_34_RIGHT,
    CaptureType.EXT_ROOF,
)


class QualityGateFailure(StrEnum):
    """Client-side capture rejection reasons. Messages live in the web app's
    i18n bundle in Bahasa Indonesia; the codes are stable identifiers."""

    BLUR = "BLUR"
    GLARE = "GLARE"
    UNDEREXPOSED = "UNDEREXPOSED"
    RESOLUTION_TOO_LOW = "RESOLUTION_TOO_LOW"
    NO_TEXT_REGION = "NO_TEXT_REGION"


# --------------------------------------------------------------------------
# ICR / cross-checks
# --------------------------------------------------------------------------


class CrossCheckType(StrEnum):
    VIN_MATCH = "VIN_MATCH"
    ENGINE_NO_MATCH = "ENGINE_NO_MATCH"
    TAX_STATUS = "TAX_STATUS"
    ODOMETER_SANITY = "ODOMETER_SANITY"
    PHOTO_REUSE = "PHOTO_REUSE"
    FIELD_CONFIDENCE = "FIELD_CONFIDENCE"
    PLATE_CONDITION = "PLATE_CONDITION"
    VIN_DECODE_AGREEMENT = "VIN_DECODE_AGREEMENT"


class CheckVerdict(StrEnum):
    PASS = "PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MISMATCH = "MISMATCH"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CheckSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    #: BLOCKER stops auto-progression through the state machine (§8.6).
    BLOCKER = "BLOCKER"


class TaxStatus(StrEnum):
    """Derived from the STNK tax panel `berlaku_sampai` only.

    There is no Samsat integration. EXPIRED_GTE_12M is a material cost item
    (progressive penalty plus re-registration) and is surfaced prominently.
    """

    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED_LT_12M = "EXPIRED_LT_12M"
    EXPIRED_GTE_12M = "EXPIRED_GTE_12M"
    UNKNOWN = "UNKNOWN"


class PlateCondition(StrEnum):
    CLEAN = "CLEAN"
    RUST_LIGHT = "RUST_LIGHT"
    RUST_HEAVY = "RUST_HEAVY"
    REPAINTED = "REPAINTED"
    SCRATCHED_OVER = "SCRATCHED_OVER"
    #: Fraud signal, not a cosmetic one. Hard-blocks auto-approval.
    TAMPERED_SUSPECTED = "TAMPERED_SUSPECTED"
    ILLEGIBLE = "ILLEGIBLE"


class OcrProviderName(StrEnum):
    STUB = "stub"
    PADDLE = "paddle"
    CLOUD_DOCAI = "cloud_docai"


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


class Transmission(StrEnum):
    """STNK does not record transmission. This is resolved via the variant
    catalog or by mandatory manual selection (§6.1)."""

    MT = "MT"
    AT = "AT"
    CVT = "CVT"
    AMT = "AMT"
    DCT = "DCT"
    UNKNOWN = "UNKNOWN"


class BodyType(StrEnum):
    MPV = "mpv"
    SUV = "suv"
    HATCHBACK = "hatchback"
    SEDAN = "sedan"
    PICKUP = "pickup"
    VAN = "van"
    WAGON = "wagon"
    COUPE = "coupe"
    UNKNOWN = "unknown"


class FuelType(StrEnum):
    BENSIN = "bensin"
    SOLAR = "solar"
    HYBRID = "hybrid"
    LISTRIK = "listrik"
    UNKNOWN = "unknown"


class VariantResolutionMethod(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"
    #: Pricing confidence must degrade when a unit is UNRESOLVED (§6.1).
    UNRESOLVED = "unresolved"


# --------------------------------------------------------------------------
# Damage and grading
# --------------------------------------------------------------------------


class Panel(StrEnum):
    FRONT_BUMPER = "front_bumper"
    REAR_BUMPER = "rear_bumper"
    HOOD = "hood"
    ROOF = "roof"
    TRUNK_TAILGATE = "trunk_tailgate"
    FENDER_FL = "fender_fl"
    FENDER_FR = "fender_fr"
    DOOR_FL = "door_fl"
    DOOR_FR = "door_fr"
    DOOR_RL = "door_rl"
    DOOR_RR = "door_rr"
    QUARTER_PANEL_L = "quarter_panel_l"
    QUARTER_PANEL_R = "quarter_panel_r"
    WINDSHIELD = "windshield"
    REAR_GLASS = "rear_glass"
    HEADLAMP_L = "headlamp_l"
    HEADLAMP_R = "headlamp_r"
    TAILLAMP_L = "taillamp_l"
    TAILLAMP_R = "taillamp_r"
    GRILLE = "grille"
    MIRROR_L = "mirror_l"
    MIRROR_R = "mirror_r"
    WHEEL_FL = "wheel_fl"
    WHEEL_FR = "wheel_fr"
    WHEEL_RL = "wheel_rl"
    WHEEL_RR = "wheel_rr"
    TIRE_FL = "tire_fl"
    TIRE_FR = "tire_fr"
    TIRE_RL = "tire_rl"
    TIRE_RR = "tire_rr"


class PanelGroup(StrEnum):
    """Coarse grouping used for pricing features (§8.1) so the model does not
    see 30 sparse per-panel columns."""

    FRONT = "front"
    REAR = "rear"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    GLASS = "glass"
    LIGHTING = "lighting"
    WHEELS = "wheels"


PANEL_GROUPS: dict[Panel, PanelGroup] = {
    Panel.FRONT_BUMPER: PanelGroup.FRONT,
    Panel.GRILLE: PanelGroup.FRONT,
    Panel.HOOD: PanelGroup.FRONT,
    Panel.REAR_BUMPER: PanelGroup.REAR,
    Panel.TRUNK_TAILGATE: PanelGroup.REAR,
    Panel.ROOF: PanelGroup.TOP,
    Panel.FENDER_FL: PanelGroup.LEFT,
    Panel.DOOR_FL: PanelGroup.LEFT,
    Panel.DOOR_RL: PanelGroup.LEFT,
    Panel.QUARTER_PANEL_L: PanelGroup.LEFT,
    Panel.MIRROR_L: PanelGroup.LEFT,
    Panel.FENDER_FR: PanelGroup.RIGHT,
    Panel.DOOR_FR: PanelGroup.RIGHT,
    Panel.DOOR_RR: PanelGroup.RIGHT,
    Panel.QUARTER_PANEL_R: PanelGroup.RIGHT,
    Panel.MIRROR_R: PanelGroup.RIGHT,
    Panel.WINDSHIELD: PanelGroup.GLASS,
    Panel.REAR_GLASS: PanelGroup.GLASS,
    Panel.HEADLAMP_L: PanelGroup.LIGHTING,
    Panel.HEADLAMP_R: PanelGroup.LIGHTING,
    Panel.TAILLAMP_L: PanelGroup.LIGHTING,
    Panel.TAILLAMP_R: PanelGroup.LIGHTING,
    Panel.WHEEL_FL: PanelGroup.WHEELS,
    Panel.WHEEL_FR: PanelGroup.WHEELS,
    Panel.WHEEL_RL: PanelGroup.WHEELS,
    Panel.WHEEL_RR: PanelGroup.WHEELS,
    Panel.TIRE_FL: PanelGroup.WHEELS,
    Panel.TIRE_FR: PanelGroup.WHEELS,
    Panel.TIRE_RL: PanelGroup.WHEELS,
    Panel.TIRE_RR: PanelGroup.WHEELS,
}


class DamageType(StrEnum):
    BARET = "baret"  # scratch
    PENYOK = "penyok"  # dent
    KARAT = "karat"  # rust
    CAT_ULANG = "cat_ulang"  # repaint / colour mismatch
    RETAK = "retak"  # crack
    PECAH = "pecah"  # broken / shattered
    #: Strongest exterior-visible proxy for prior collision repair. Weighted
    #: distinctly and higher than an equivalent-area scratch (§7.2).
    CELAH_PANEL = "celah_panel"  # panel gap / misalignment
    KOMPONEN_HILANG = "komponen_hilang"  # missing part


#: Severity 1 = minor (polish), 2 = moderate (panel work), 3 = severe (replace).
SEVERITY_LEVELS: tuple[int, int, int] = (1, 2, 3)


class DetectionSource(StrEnum):
    AI = "ai"
    INSPECTOR = "inspector"
    APPRAISER = "appraiser"


class CorrectionAction(StrEnum):
    """Written to the label store; this is the Stage 2 training set (§7.3)."""

    CONFIRM = "confirm"
    EDIT = "edit"
    DELETE = "delete"
    ADD = "add"


class GradeSource(StrEnum):
    AI = "ai"
    FINAL = "final"


class VisionProviderName(StrEnum):
    STUB = "stub"
    VLM = "vlm"
    YOLO = "yolo"


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------


class SellerType(StrEnum):
    LEASING = "leasing"
    FLEET = "fleet"
    INDIVIDUAL = "individual"
    DEALER = "dealer"


class AuctionOutcome(StrEnum):
    """Unsold units are left-censored observations, not missing data (§8.3)."""

    SOLD = "sold"
    NO_BID = "no_bid"
    BELOW_RESERVE = "below_reserve"


class DataSufficiencyTier(StrEnum):
    RICH = "RICH"
    MODERATE = "MODERATE"
    THIN = "THIN"
    COLD_START = "COLD_START"


class PriceConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PricingModelKind(StrEnum):
    LGBM_QUANTILE = "lgbm_quantile"
    #: Baseline for comparison and explainability only - never the production
    #: model (§8.2).
    OLS_BASELINE = "ols_baseline"
    RIDGE_BASELINE = "ridge_baseline"
    RESIDUAL_ANCHOR = "residual_anchor"


# --------------------------------------------------------------------------
# Non-visual checklist (§8.4)
# --------------------------------------------------------------------------


class NonVisualCheckItem(StrEnum):
    """Exterior-only AI grading cannot see any of these. A flagged item blocks
    auto-approval. The exact item list is [TBC] - see docs/OPEN_ITEMS.md #6."""

    FLOOD_INDICATION = "flood_indication"
    CHASSIS_REPAIR = "chassis_repair"
    ENGINE_CONDITION = "engine_condition"
    TRANSMISSION_CONDITION = "transmission_condition"
    ODOMETER_TAMPERING = "odometer_tampering"
    AIRBAG_DEPLOYED = "airbag_deployed"
    DOCUMENT_COMPLETENESS = "document_completeness"


class ChecklistAnswer(StrEnum):
    OK = "ok"
    FLAGGED = "flagged"
    NOT_CHECKED = "not_checked"


# --------------------------------------------------------------------------
# Jobs and audit
# --------------------------------------------------------------------------


class JobType(StrEnum):
    ICR_EXTRACT = "icr_extract"
    CROSS_CHECK = "cross_check"
    VISION_DETECT = "vision_detect"
    GRADE_COMPUTE = "grade_compute"
    PRICE_COMPUTE = "price_compute"
    PHASH_INDEX = "phash_index"
    PII_PURGE = "pii_purge"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    STATUS_TRANSITION = "status_transition"
    OVERRIDE = "override"
    APPROVE = "approve"
    REJECT = "reject"
    PII_ACCESS = "pii_access"
    LOGIN = "login"
    CONFIG_CHANGE = "config_change"
