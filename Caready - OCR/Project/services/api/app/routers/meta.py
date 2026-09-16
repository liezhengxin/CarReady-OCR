"""System metadata: config versions, capability map, and disclosure banners.

The web app reads `/api/meta/system` on load to decide which warning banners to
show. Keeping that decision server-side means a synthetic-data or
placeholder-rubric deployment cannot be made to look like a production one by
editing client code.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import config_version, get_settings, grading_is_placeholder, load_config
from app.enums import ROLE_CAPABILITIES, Role

router = APIRouter(prefix="/api/meta", tags=["meta"])
settings = get_settings()

SYNTHETIC_BANNER_ID = "synthetic_data"
PLACEHOLDER_RUBRIC_BANNER_ID = "placeholder_grading_rubric"
COLDSTART_BANNER_ID = "coldstart_deduction_table"


class Banner(BaseModel):
    id: str
    severity: str = Field(description="info | warning | critical")
    title_id: str = Field(description="Bahasa Indonesia title")
    body_id: str = Field(description="Bahasa Indonesia body")
    dismissible: bool


class SystemMeta(BaseModel):
    environment: str
    api_version: str
    synthetic_data_mode: bool
    grading_rubric_placeholder: bool
    config_versions: dict[str, str]
    banners: list[Banner]


def _banners() -> list[Banner]:
    banners: list[Banner] = []

    if settings.synthetic_data_mode:
        # Required by §9. Not dismissible: the whole point is that nobody can
        # mistake synthetic output for a real valuation, including someone who
        # dismissed the banner an hour ago.
        banners.append(
            Banner(
                id=SYNTHETIC_BANNER_ID,
                severity="critical",
                title_id="DATA SINTETIS - BUKAN DATA NYATA",
                body_id=(
                    "Seluruh data pada sistem ini dibuat secara sintetis untuk "
                    "pengembangan. Harga yang ditampilkan TIDAK memiliki validitas "
                    "nyata dan tidak boleh digunakan sebagai dasar keputusan lelang."
                ),
                dismissible=False,
            )
        )

    if grading_is_placeholder():
        banners.append(
            Banner(
                id=PLACEHOLDER_RUBRIC_BANNER_ID,
                severity="warning",
                title_id="Rubrik grading masih placeholder",
                body_id=(
                    "Skala dan rubrik grading yang aktif belum dikonfirmasi oleh "
                    "Caready. Grade yang dihasilkan bersifat sementara dan "
                    "menurunkan tingkat keyakinan harga."
                ),
                dismissible=True,
            )
        )

    coldstart = load_config("deduction_coldstart")
    if str(coldstart.get("status", "")).upper() == "PLACEHOLDER":
        banners.append(
            Banner(
                id=COLDSTART_BANNER_ID,
                severity="warning",
                title_id="Tabel potongan cold-start belum dikalibrasi",
                body_id=(
                    "Tabel potongan cold-start belum pernah dikalibrasi terhadap "
                    "harga realisasi. Potongan yang berasal dari tabel ini ditandai "
                    "secara eksplisit pada hasil harga."
                ),
                dismissible=True,
            )
        )

    return banners


@router.get("/system", response_model=SystemMeta)
def system_meta() -> SystemMeta:
    return SystemMeta(
        environment=settings.environment,
        api_version="0.1.0",
        synthetic_data_mode=settings.synthetic_data_mode,
        grading_rubric_placeholder=grading_is_placeholder(),
        config_versions={
            name: config_version(name)
            for name in ("grading", "pricing", "crosschecks", "capture", "catalog", "pdp", "providers")
        },
        banners=_banners(),
    )


@router.get("/capabilities")
def capability_map() -> dict[str, list[str]]:
    """The role to capability mapping.

    Exposed so the client can hide what a user cannot do. This is a
    convenience for the UI only - every endpoint enforces its own capability
    server-side, and price fields are omitted from responses rather than
    hidden by the client.
    """
    return {role.value: sorted(c.value for c in caps) for role, caps in ROLE_CAPABILITIES.items()}


@router.get("/enums")
def enum_values() -> dict[str, list[str]]:
    """Enumerated vocabularies, for client-side dropdowns and validation.

    Served from the same `app.enums` module the database constraints are built
    from, so the client cannot drift from the schema.
    """
    from app.enums import (
        BodyType,
        CaptureType,
        DamageType,
        NonVisualCheckItem,
        Panel,
        PlateCondition,
        SellerType,
        TaxStatus,
        Transmission,
        UnitStatus,
    )

    return {
        "unit_status": UnitStatus.values(),
        "capture_type": CaptureType.values(),
        "panel": Panel.values(),
        "damage_type": DamageType.values(),
        "plate_condition": PlateCondition.values(),
        "tax_status": TaxStatus.values(),
        "transmission": Transmission.values(),
        "body_type": BodyType.values(),
        "seller_type": SellerType.values(),
        "non_visual_check_item": NonVisualCheckItem.values(),
        "role": Role.values(),
    }
