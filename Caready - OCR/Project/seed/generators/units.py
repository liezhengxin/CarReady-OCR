"""Live demo units with imagery and seeded defect cases (§9).

Produces a small set of units sitting at various points in the workflow, so the
dashboard has something to show and the M2 acceptance criterion has fixtures to
assert against.

SEEDED DEFECT CASES
-------------------
Planted at fixed indices so tests can reference them by unit code rather than
by scanning for them:

    SYN-U-0000  VIN mismatch          plate VIN differs from STNK nomor_rangka
                                      beyond the fuzzy threshold -> MISMATCH
    SYN-U-0001  VIN near-match        differs by 1 character     -> NEEDS_REVIEW
    SYN-U-0002  OCR-ambiguity match   differs only by O/0 and I/1; must PASS
                                      with normalisation_applied = True
    SYN-U-0003  engine number mismatch                           -> MISMATCH
    SYN-U-0004  tampered plate        TAMPERED_SUSPECTED         -> BLOCKER
    SYN-U-0005  odometer rollback     8-year-old unit at 9,000km -> BLOCKER
    SYN-U-0006  photo reuse           STNK image byte-identical to SYN-U-0000
    SYN-U-0007  expired tax >= 12m    material cost item, surfaced prominently
    SYN-U-0008  unresolved variant    `tipe` matches no catalog entry
    SYN-U-0009  low OCR confidence    fields below threshold -> review queue

Every other unit is clean. The clean/defect ratio here is not a claim about
real-world fraud rates - it is chosen so each code path has coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .catalog_spec import BrandSpec, GenerationSpec, ModelSpec, VariantSpec, iter_variants
from .common import (
    BRANCHES,
    BRAND_SHARE,
    COLOUR_SHARE,
    GRADE_SCORE_RANGE,
    GRADE_SHARE,
    HISTORY_END,
    SELLER_TYPE_SHARE,
    stream,
    synthetic_address,
    synthetic_engine_no,
    synthetic_name,
    synthetic_plate,
    synthetic_vin,
    weighted_choice,
)

#: Small on purpose. These carry imagery, so the count drives seed runtime and
#: disk more than anything else in the seeder.
DEMO_UNIT_COUNT = 40

#: Index -> defect case. See the module docstring.
DEFECT_CASES: dict[int, str] = {
    0: "vin_mismatch",
    1: "vin_near_match",
    2: "vin_ocr_ambiguity",
    3: "engine_no_mismatch",
    4: "tampered_plate",
    5: "odometer_rollback",
    6: "photo_reuse",
    7: "tax_expired_long",
    8: "unresolved_variant",
    9: "low_ocr_confidence",
}

#: Where each demo unit sits in the workflow, so the dashboard has a realistic
#: spread of queues rather than forty identical rows.
STATUS_MIX = {
    "DRAFT": 0.10,
    "ICR_DONE": 0.15,
    "GRADED": 0.15,
    "PRICED": 0.15,
    "PENDING_APPROVAL": 0.25,
    "APPROVED": 0.15,
    "REJECTED": 0.05,
}


@dataclass
class DemoUnit:
    index: int
    code: str
    defect_case: str | None
    status: str
    branch_code: str

    brand: str
    model: str
    generation: str
    variant_code: str
    variant_trim: str
    transmission: str
    body_type: str
    engine_cc: int
    fuel_type: str

    model_year: int
    odometer_km: int
    colour: str
    seller_type: str

    # STNK values, as they appear on the document.
    nomor_registrasi: str
    nama_pemilik: str
    alamat: str
    merk: str
    tipe: str
    jenis: str
    stnk_model: str
    nomor_rangka: str
    nomor_mesin: str
    warna: str
    bahan_bakar: str
    warna_tnkb: str
    tahun_registrasi: int
    nomor_bpkb: str
    kode_lokasi: str
    berlaku_sampai: date
    tanggal_pajak: date
    tax_status: str

    # What the plate photos actually show. Differs from the STNK values in the
    # seeded mismatch cases - that difference is the thing being tested.
    plate_vin_text: str
    plate_engine_text: str
    plate_condition: str

    grade_label: str
    damage_score: float
    celah_panel_present: bool
    rust_present: bool
    repaint_present: bool

    #: Per-field OCR confidence the stub provider will report.
    field_confidence: dict[str, float] = field(default_factory=dict)
    #: Non-visual checklist answers (§8.4).
    checklist: dict[str, str] = field(default_factory=dict)
    checklist_notes: dict[str, str] = field(default_factory=dict)
    #: Expected cross-check verdicts, asserted by the M2 tests.
    expected_verdicts: dict[str, str] = field(default_factory=dict)


def _tax_dates(rng, status: str, today: date) -> tuple[date, date, str]:
    if status == "ACTIVE":
        valid_until = today + timedelta(days=rng.randint(40, 330))
    elif status == "EXPIRING_SOON":
        valid_until = today + timedelta(days=rng.randint(1, 30))
    elif status == "EXPIRED_LT_12M":
        valid_until = today - timedelta(days=rng.randint(10, 350))
    else:
        valid_until = today - timedelta(days=rng.randint(400, 1100))
    return valid_until, valid_until - timedelta(days=365), status


def _pick_variant(rng) -> tuple[BrandSpec, ModelSpec, GenerationSpec, VariantSpec]:
    pool = list(iter_variants())
    weights = [BRAND_SHARE.get(b.name, 0.01) * m.share for b, m, _, _ in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


def _confidence_profile(rng, low: bool) -> dict[str, float]:
    """Per-field OCR confidence.

    When `low`, the pricing- and identity-critical fields are pushed below the
    thresholds in config/crosschecks.yaml so the unit routes to the human
    verification queue. Everything else stays comfortably above, so the test
    asserts routing on the intended fields rather than on a blanket failure.
    """
    base = {
        "nomor_registrasi": 0.96, "nama_pemilik": 0.91, "alamat": 0.86,
        "merk": 0.97, "tipe": 0.93, "jenis": 0.95, "model": 0.94,
        "tahun_pembuatan": 0.98, "isi_silinder": 0.95, "nomor_rangka": 0.97,
        "nomor_mesin": 0.96, "warna": 0.92, "bahan_bakar": 0.94,
        "warna_tnkb": 0.90, "tahun_registrasi": 0.93, "nomor_bpkb": 0.89,
        "kode_lokasi": 0.88, "berlaku_sampai": 0.95, "odometer_km": 0.94,
    }
    jitter = {k: round(min(0.995, max(0.30, v + rng.uniform(-0.06, 0.02))), 3) for k, v in base.items()}
    if low:
        jitter.update({
            "nomor_rangka": 0.71,   # threshold 0.92
            "tahun_pembuatan": 0.62,  # threshold 0.90
            "odometer_km": 0.58,    # threshold 0.90
            "tipe": 0.49,           # threshold 0.85
        })
    return jitter


def _checklist(rng, defect: str | None) -> tuple[dict[str, str], dict[str, str]]:
    """Non-visual checklist answers (§8.4).

    Most units come back clean. A small share carry a flag, which must block
    auto-approval - without this gate, mechanically damaged units are
    systematically overpriced because exterior AI grading cannot see any of it.
    """
    items = [
        "flood_indication", "chassis_repair", "engine_condition",
        "transmission_condition", "odometer_tampering", "airbag_deployed",
        "document_completeness",
    ]
    answers = {item: "ok" for item in items}
    notes: dict[str, str] = {}

    if defect == "odometer_rollback":
        answers["odometer_tampering"] = "flagged"
        notes["odometer_tampering"] = "Kilometer tidak wajar untuk usia kendaraan, dugaan reset."
    elif rng.random() < 0.18:
        flagged = rng.choice(items)
        answers[flagged] = "flagged"
        notes[flagged] = {
            "flood_indication": "Ditemukan endapan lumpur pada jalur kabel bawah karpet.",
            "chassis_repair": "Terdapat bekas las pada rangka bagian depan.",
            "engine_condition": "Suara mesin kasar saat idle, asap putih tipis.",
            "transmission_condition": "Perpindahan gigi menghentak pada posisi 2-3.",
            "odometer_tampering": "Selisih data servis dengan angka odometer.",
            "airbag_deployed": "Cover airbag pernah dibuka, indikator menyala.",
            "document_completeness": "BPKB tidak tersedia saat inspeksi.",
        }[flagged]
    return answers, notes


def generate_demo_units() -> list[DemoUnit]:
    rng = stream("units")
    today = HISTORY_END
    units: list[DemoUnit] = []

    for i in range(DEMO_UNIT_COUNT):
        defect = DEFECT_CASES.get(i)
        brand, model, generation, variant = _pick_variant(rng)

        model_year = rng.randint(
            max(generation.year_start, today.year - 12),
            min(generation.year_end or today.year, today.year - 1),
        )
        age = max(1, today.year - model_year)
        odometer = max(1_000, int(rng.gauss(15_000 * age, 15_000 * age * 0.3)))

        # --- identity ---
        true_vin = synthetic_vin(rng, brand.wmi)
        true_engine = synthetic_engine_no(rng, variant.code[:3].upper())
        plate_vin, plate_engine = true_vin, true_engine
        plate_condition = "CLEAN"
        expected: dict[str, str] = {"VIN_MATCH": "PASS", "ENGINE_NO_MATCH": "PASS"}

        if defect == "vin_mismatch":
            plate_vin = synthetic_vin(rng, brand.wmi)
            expected["VIN_MATCH"] = "MISMATCH"
        elif defect == "vin_near_match":
            # One character different: inside the fuzzy threshold of 2.
            pos = rng.randrange(4, 17)
            replacement = rng.choice([c for c in "23456789ABCDEFGHJKL" if c != true_vin[pos]])
            plate_vin = true_vin[:pos] + replacement + true_vin[pos + 1 :]
            expected["VIN_MATCH"] = "NEEDS_REVIEW"
        elif defect == "vin_ocr_ambiguity":
            # Only O/0 and I/1 substitutions. Must PASS after normalisation,
            # with normalisation_applied recorded on the result.
            plate_vin = true_vin.replace("0", "O").replace("1", "I")
            if plate_vin == true_vin:
                plate_vin = true_vin[:5] + "O" + true_vin[6:]
                true_vin = true_vin[:5] + "0" + true_vin[6:]
            expected["VIN_MATCH"] = "PASS"
        elif defect == "engine_no_mismatch":
            plate_engine = synthetic_engine_no(rng, "ZZZ")
            expected["ENGINE_NO_MATCH"] = "MISMATCH"
        elif defect == "tampered_plate":
            plate_condition = "TAMPERED_SUSPECTED"
            expected["PLATE_CONDITION"] = "MISMATCH"
        elif not defect and rng.random() < 0.22:
            plate_condition = rng.choice(["RUST_LIGHT", "RUST_HEAVY", "SCRATCHED_OVER", "REPAINTED"])

        if defect == "odometer_rollback":
            model_year = today.year - 8
            age = 8
            odometer = rng.randint(7_000, 11_000)   # ~1,100 km/yr -> BLOCKER
            expected["ODOMETER_SANITY"] = "MISMATCH"

        tax_status = "EXPIRED_GTE_12M" if defect == "tax_expired_long" else weighted_choice(
            rng, {"ACTIVE": 0.68, "EXPIRING_SOON": 0.12, "EXPIRED_LT_12M": 0.14, "EXPIRED_GTE_12M": 0.06}
        )
        berlaku_sampai, tanggal_pajak, _ = _tax_dates(rng, tax_status, today)

        grade = weighted_choice(rng, GRADE_SHARE)
        lo, hi = GRADE_SCORE_RANGE[grade]
        colour = weighted_choice(rng, COLOUR_SHARE)

        tipe = variant.code
        if defect == "unresolved_variant":
            # A type code matching nothing in the catalog: the appraiser must
            # resolve it manually before pricing runs at all.
            tipe = f"XX-{rng.randint(10000, 99999)}-ZZ"

        checklist, notes = _checklist(rng, defect)

        units.append(
            DemoUnit(
                index=i,
                code=f"SYN-U-{i:04d}",
                defect_case=defect,
                status=weighted_choice(rng, STATUS_MIX) if not defect else "PENDING_APPROVAL",
                branch_code=weighted_choice(rng, {k: v["share"] for k, v in BRANCHES.items()}),
                brand=brand.name,
                model=model.name,
                generation=generation.name,
                variant_code=variant.code,
                variant_trim=variant.trim,
                transmission=variant.transmission,
                body_type=model.body_type,
                engine_cc=variant.engine_cc,
                fuel_type=model.fuel_type,
                model_year=model_year,
                odometer_km=odometer,
                colour=colour,
                seller_type=weighted_choice(rng, SELLER_TYPE_SHARE),
                nomor_registrasi=synthetic_plate(rng),
                nama_pemilik=synthetic_name(rng),
                alamat=synthetic_address(rng),
                merk=brand.name,
                tipe=tipe,
                jenis="MOBIL PENUMPANG" if model.body_type != "pickup" else "MOBIL BARANG",
                stnk_model=f"{model.name} {variant.trim}",
                nomor_rangka=true_vin,
                nomor_mesin=true_engine,
                warna=colour,
                bahan_bakar=model.fuel_type.upper(),
                warna_tnkb="HITAM",
                tahun_registrasi=model_year,
                nomor_bpkb=f"{rng.randint(100000, 999999)}-{rng.randint(10, 99)}",
                kode_lokasi=f"{rng.randint(1000, 9999)}",
                berlaku_sampai=berlaku_sampai,
                tanggal_pajak=tanggal_pajak,
                tax_status=tax_status,
                plate_vin_text=plate_vin,
                plate_engine_text=plate_engine,
                plate_condition=plate_condition,
                grade_label=grade,
                damage_score=round(rng.uniform(lo, hi), 2),
                celah_panel_present=rng.random() < {"A": 0.01, "B": 0.05, "C": 0.16, "D": 0.34, "E": 0.55}[grade],
                rust_present=rng.random() < {"A": 0.01, "B": 0.04, "C": 0.12, "D": 0.28, "E": 0.48}[grade],
                repaint_present=rng.random() < {"A": 0.03, "B": 0.12, "C": 0.30, "D": 0.48, "E": 0.62}[grade],
                field_confidence=_confidence_profile(rng, low=defect == "low_ocr_confidence"),
                checklist=checklist,
                checklist_notes=notes,
                expected_verdicts=expected,
            )
        )

    return units
