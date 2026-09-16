#!/usr/bin/env python
"""Seed the database with synthetic data (§9, M0).

    python seed/run_seed.py                 # full seed
    python seed/run_seed.py --no-images     # skip imagery (much faster)
    python seed/run_seed.py --reset         # truncate first

EVERYTHING WRITTEN BY THIS SCRIPT IS SYNTHETIC. Every row carries
`is_synthetic = True` where the column exists, the API serves a non-dismissible
warning banner while `SYNTHETIC_DATA_MODE` is on, and any model trained on this
data is recorded with `trained_on_synthetic = True`.

Model output derived from this data is NOT evidence of pricing accuracy. It
demonstrates that the pipeline runs end to end, nothing more.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
sys.path.insert(0, str(REPO_ROOT / "seed"))

from sqlalchemy import select, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.enums import (  # noqa: E402
    AuctionOutcome,
    BodyType,
    CaptureType,
    ChecklistAnswer,
    FuelType,
    NonVisualCheckItem,
    Role,
    SellerType,
    TaxStatus,
    Transmission,
    UnitStatus,
    VariantResolutionMethod,
)
from app.models import (  # noqa: E402
    AuctionRecord,
    Brand,
    Generation,
    NonVisualChecklistItem,
    OtrPrice,
    OtrPriceSnapshot,
    Photo,
    Unit,
    UnitStatusTransition,
    UnitStnkData,
    User,
    Variant,
    VehicleModel,
)
from app.security import hash_password  # noqa: E402
from generators import auction as auction_gen  # noqa: E402
from generators import images as image_gen  # noqa: E402
from generators import otr as otr_gen  # noqa: E402
from generators import units as unit_gen  # noqa: E402
from generators.catalog_spec import CATALOG  # noqa: E402
from generators.common import MASTER_SEED, stream  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "seed" / "output"
IMAGE_DIR = OUTPUT_DIR / "images"
FIXTURE_OCR_DIR = REPO_ROOT / "seed" / "fixtures" / "ocr"
FIXTURE_VISION_DIR = REPO_ROOT / "seed" / "fixtures" / "vision"

#: Demo accounts. Passwords are intentionally obvious - these exist only for a
#: local synthetic stack and the seeder refuses to run against `prod`.
DEMO_USERS = [
    ("inspektur@caready.local", "Rudi Inspektur", Role.INSPECTOR, "JKT-01"),
    ("inspektur2@caready.local", "Sari Inspektur", Role.INSPECTOR, "SBY-01"),
    ("penilai@caready.local", "Dewi Penilai", Role.APPRAISER, "JKT-01"),
    ("penyetuju@caready.local", "Agus Penyetuju", Role.APPROVER, "JKT-01"),
    ("admin@caready.local", "Admin Caready", Role.ADMIN, None),
]
DEMO_PASSWORD = "caready-dev-2026"

TRANSMISSION_MAP = {"MT": Transmission.MT, "AT": Transmission.AT, "CVT": Transmission.CVT}
BODY_MAP = {b.value: b for b in BodyType}
FUEL_MAP = {"bensin": FuelType.BENSIN, "solar": FuelType.SOLAR, "hybrid": FuelType.HYBRID}


def log(message: str) -> None:
    print(f"[seed] {message}", flush=True)


def normalise(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum() or ch == " ").strip()


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------


def seed_users(session) -> dict[str, User]:
    existing = {u.email: u for u in session.execute(select(User)).scalars()}
    out: dict[str, User] = {}
    for email, name, role, branch in DEMO_USERS:
        if email in existing:
            out[email] = existing[email]
            continue
        user = User(
            email=email,
            full_name=name,
            password_hash=hash_password(DEMO_PASSWORD),
            role=role,
            branch_code=branch,
        )
        session.add(user)
        out[email] = user
    session.flush()
    log(f"users: {len(out)}")
    return out


def seed_catalog(session) -> dict[str, Variant]:
    """Create the catalog and return a variant-code -> Variant index."""
    by_code: dict[str, Variant] = {}
    for brand_spec in CATALOG:
        brand = Brand(
            name=brand_spec.name,
            normalized_name=normalise(brand_spec.name),
            country=brand_spec.country,
        )
        session.add(brand)
        session.flush()

        for model_spec in brand_spec.models:
            model = VehicleModel(
                brand_id=brand.id,
                name=model_spec.name,
                normalized_name=normalise(model_spec.name),
                segment=model_spec.segment,
            )
            session.add(model)
            session.flush()

            for gen_spec in model_spec.generations:
                generation = Generation(
                    vehicle_model_id=model.id,
                    name=gen_spec.name,
                    year_start=gen_spec.year_start,
                    year_end=gen_spec.year_end,
                )
                session.add(generation)
                session.flush()

                for variant_spec in gen_spec.variants:
                    variant = Variant(
                        generation_id=generation.id,
                        trim=variant_spec.trim,
                        normalized_trim=normalise(variant_spec.trim),
                        transmission=TRANSMISSION_MAP[variant_spec.transmission],
                        body_type=BODY_MAP.get(model_spec.body_type, BodyType.UNKNOWN),
                        fuel_type=FUEL_MAP.get(model_spec.fuel_type, FuelType.UNKNOWN),
                        engine_cc=variant_spec.engine_cc,
                        notes=f"synthetic catalog entry; type code {variant_spec.code}",
                    )
                    session.add(variant)
                    session.flush()
                    by_code[variant_spec.code] = variant

    log(f"catalog: {len(CATALOG)} brands, {len(by_code)} variants")
    return by_code


def seed_otr(session, variants: dict[str, Variant]) -> list:
    rows = otr_gen.generate_otr_series()
    snapshot = OtrPriceSnapshot(
        source="synthetic-generator",
        adapter="csv",
        adapter_version="0.1.0",
        url=None,
        http_status=None,
        row_count=len(rows),
        succeeded=True,
        is_synthetic=True,
    )
    session.add(snapshot)
    session.flush()

    session.bulk_save_objects(
        [
            OtrPrice(
                snapshot_id=snapshot.id,
                variant_id=variants[row.code].id if row.code in variants else None,
                raw_label=row.raw_label,
                model_year=row.effective_date.year,
                region="nasional",
                price_idr=row.price_idr,
                effective_date=row.effective_date,
                is_synthetic=True,
            )
            for row in rows
        ]
    )
    log(f"otr prices: {len(rows)} rows across {len({r.code for r in rows})} variants")
    return rows


def seed_auctions(session, variants: dict[str, Variant], otr_rows: list) -> dict[str, float]:
    lookup = otr_gen.build_otr_lookup(otr_rows)
    rows = auction_gen.generate_auction_records(lookup)

    outcome_map = {
        "sold": AuctionOutcome.SOLD,
        "no_bid": AuctionOutcome.NO_BID,
        "below_reserve": AuctionOutcome.BELOW_RESERVE,
    }
    seller_map = {s.value: s for s in SellerType}
    tax_map = {t.value: t for t in TaxStatus}
    trans_map = {"MT": Transmission.MT, "AT": Transmission.AT, "CVT": Transmission.CVT}

    batch: list[AuctionRecord] = []
    for row in rows:
        variant = variants.get(row.variant_code)
        batch.append(
            AuctionRecord(
                external_ref=row.external_ref,
                variant_id=variant.id if variant else None,
                raw_merk=row.raw_merk,
                raw_tipe=row.raw_tipe,
                raw_model=row.raw_model,
                model_year=row.model_year,
                transmission=trans_map.get(row.transmission) if row.transmission else None,
                odometer_km=row.odometer_km,
                colour=row.colour,
                engine_cc=row.engine_cc,
                grade_label=row.grade_label,
                damage_score=row.damage_score,
                celah_panel_present=row.celah_panel_present,
                rust_present=row.rust_present,
                repaint_present=row.repaint_present,
                tax_status=tax_map.get(row.tax_status),
                auction_date=row.auction_date,
                auction_location=row.auction_location,
                seller_type=seller_map.get(row.seller_type),
                outcome=outcome_map[row.outcome],
                sale_price=row.sale_price,
                reserve_price=row.reserve_price,
                highest_bid=row.highest_bid,
                bidder_count=row.bidder_count,
                otr_price_at_auction=row.otr_price_at_auction,
                is_synthetic=True,
            )
        )
        if len(batch) >= 2000:
            session.bulk_save_objects(batch)
            session.flush()
            batch = []
    if batch:
        session.bulk_save_objects(batch)
        session.flush()

    summary = auction_gen.summarise(rows)
    log(
        "auction records: {total_rows:.0f} rows | sold {sold_share:.1%} | "
        "no-bid {no_bid_share:.1%} | below-reserve {below_reserve_share:.1%} | "
        "median residual {median_residual_ratio:.3f}".format(**summary)
    )
    log(
        "  imperfections: missing odo {missing_odometer_share:.1%} | "
        "missing grade {missing_grade_share:.1%} | "
        "missing transmission {missing_transmission_share:.1%} | "
        "duplicates {duplicate_share:.2%} | outliers {outlier_share:.2%}".format(**summary)
    )
    return summary


def seed_units(session, users: dict[str, User], variants: dict[str, Variant], with_images: bool) -> int:
    demo_units = unit_gen.generate_demo_units()
    inspector = users["inspektur@caready.local"]
    rng = stream("unit-images")
    generated_images: list[image_gen.GeneratedImage] = []

    status_map = {s.value: s for s in UnitStatus}
    tax_map = {t.value: t for t in TaxStatus}
    seller_map = {s.value: s for s in SellerType}

    # For the photo-reuse case: capture the first unit's STNK bytes and reuse
    # them verbatim on SYN-U-0006, so the perceptual-hash collision is exact.
    reuse_source: image_gen.GeneratedImage | None = None

    for du in demo_units:
        variant = variants.get(du.variant_code)
        unit = Unit(
            code=du.code,
            status=status_map[du.status],
            created_by_id=inspector.id,
            branch_code=du.branch_code,
            client_draft_id=uuid.uuid4(),
            intake_complete=True,
            variant_id=variant.id if variant and du.defect_case != "unresolved_variant" else None,
            variant_resolution_method=(
                VariantResolutionMethod.UNRESOLVED
                if du.defect_case == "unresolved_variant"
                else VariantResolutionMethod.AUTO
            ),
            variant_match_score=None if du.defect_case == "unresolved_variant" else 96.0,
            model_year=du.model_year,
            odometer_km=du.odometer_km,
            colour=du.colour,
            tax_status=tax_map[du.tax_status],
            tax_valid_until=du.berlaku_sampai,
            seller_type=seller_map[du.seller_type],
        )
        session.add(unit)
        session.flush()

        session.add(
            UnitStnkData(
                unit_id=unit.id,
                nomor_registrasi=du.nomor_registrasi,
                nama_pemilik=du.nama_pemilik,
                alamat=du.alamat,
                nik=None,
                nomor_bpkb=du.nomor_bpkb,
                merk=du.merk,
                tipe=du.tipe,
                jenis=du.jenis,
                model=du.stnk_model,
                tahun_pembuatan=du.model_year,
                isi_silinder=du.engine_cc,
                nomor_rangka=du.nomor_rangka,
                nomor_mesin=du.nomor_mesin,
                warna=du.warna,
                bahan_bakar=du.bahan_bakar,
                warna_tnkb=du.warna_tnkb,
                tahun_registrasi=du.tahun_registrasi,
                kode_lokasi=du.kode_lokasi,
                berlaku_sampai=du.berlaku_sampai,
                tanggal_pajak=du.tanggal_pajak,
                field_confidence=du.field_confidence,
            )
        )

        for item, answer in du.checklist.items():
            session.add(
                NonVisualChecklistItem(
                    unit_id=unit.id,
                    item=NonVisualCheckItem(item),
                    answer=ChecklistAnswer(answer),
                    note=du.checklist_notes.get(item),
                    answered_by_id=inspector.id,
                    answered_at=datetime.now(UTC),
                )
            )

        # Initial DRAFT transition. Later transitions are written by the
        # workflow itself at M7; seeding them here would fabricate an audit
        # trail for actions nobody took.
        session.add(
            UnitStatusTransition(
                unit_id=unit.id,
                from_status=None,
                to_status=UnitStatus.DRAFT,
                actor_id=inspector.id,
                actor_email=inspector.email,
                actor_role=inspector.role.value,
                automated=False,
                reason="Synthetic seed data",
            )
        )

        if with_images:
            reuse_source = _generate_unit_images(
                du, rng, generated_images, reuse_source, session, unit, inspector
            )

    if with_images:
        image_gen.write_fixtures(generated_images, FIXTURE_OCR_DIR, FIXTURE_VISION_DIR)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "image_manifest.json").write_text(
            json.dumps(image_gen.manifest(generated_images), indent=2, default=str), encoding="utf-8"
        )
        log(f"images: {len(generated_images)} files -> {IMAGE_DIR}")

    log(f"demo units: {len(demo_units)} ({len(unit_gen.DEFECT_CASES)} seeded defect cases)")
    return len(demo_units)


def _generate_unit_images(du, rng, collected, reuse_source, session, unit, inspector):
    """Render one unit's captures and register them as Photo rows.

    Photos are written to the local filesystem under seed/output/images and
    registered with an `s3_key` pointing at where the uploader would have put
    them. A separate step pushes them into MinIO; the DB rows are valid either
    way, which keeps the seeder usable without object storage running.
    """
    unit_dir = IMAGE_DIR / du.code
    stnk_values = {
        "nomor_registrasi": du.nomor_registrasi,
        "nama_pemilik": du.nama_pemilik,
        "alamat": du.alamat,
        "merk": du.merk,
        "tipe": du.tipe,
        "jenis": du.jenis,
        "model": du.stnk_model,
        "tahun_pembuatan": du.model_year,
        "isi_silinder": du.engine_cc,
        "nomor_rangka": du.nomor_rangka,
        "nomor_mesin": du.nomor_mesin,
        "warna": du.warna,
        "bahan_bakar": du.bahan_bakar,
        "warna_tnkb": du.warna_tnkb,
        "tahun_registrasi": du.tahun_registrasi,
        "nomor_bpkb": du.nomor_bpkb,
        "kode_lokasi": du.kode_lokasi,
        "berlaku_sampai": du.berlaku_sampai.strftime("%d-%m-%Y"),
        "tanggal_pajak": du.tanggal_pajak.strftime("%d-%m-%Y"),
    }

    def pick_degradation() -> image_gen.Degradation:
        name = rng.choices(
            list(image_gen.DEGRADATION_SHARE),
            weights=list(image_gen.DEGRADATION_SHARE.values()),
            k=1,
        )[0]
        return next(d for d in image_gen.DEGRADATIONS if d.name == name)

    def register(path: Path, sha: str, capture_type: str, deg, truth: dict) -> None:
        rel = path.relative_to(REPO_ROOT).as_posix()
        collected.append(
            image_gen.GeneratedImage(
                path=rel,
                sha256=sha,
                capture_type=capture_type,
                degradation=deg.name,
                expect_gate_rejection=deg.expect_gate_rejection,
                truth=truth,
            )
        )
        failures = None
        if deg.name == "blurred":
            failures = ["BLUR"]
        elif deg.name == "dark":
            failures = ["UNDEREXPOSED"]
        session.add(
            Photo(
                unit_id=unit.id,
                capture_type=CaptureType(capture_type),
                s3_key_original=f"units/{du.code}/{capture_type.lower()}.jpg",
                size_bytes=path.stat().st_size,
                sha256=sha,
                uploaded_by_id=inspector.id,
                device_fingerprint=f"synthetic-device-{du.index % 5}",
                quality_passed=not deg.expect_gate_rejection,
                quality_failures=failures,
                idempotency_key=uuid.uuid4(),
            )
        )

    # --- STNK ---
    if du.defect_case == "photo_reuse" and reuse_source is not None:
        # Byte-identical reuse of an earlier unit's document, which is exactly
        # what the perceptual-hash check exists to catch.
        src = REPO_ROOT / reuse_source.path
        dst = unit_dir / "intake_stnk_front.jpg"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        register(dst, reuse_source.sha256, "INTAKE_STNK_FRONT", image_gen.DEGRADATIONS[0], reuse_source.truth)
    else:
        deg = pick_degradation()
        img = image_gen.draw_stnk(stnk_values, deg, rng)
        path = unit_dir / "intake_stnk_front.jpg"
        sha = image_gen.save_jpeg(img, path)
        truth = {"kind": "stnk", "fields": stnk_values, "confidence": du.field_confidence}
        register(path, sha, "INTAKE_STNK_FRONT", deg, truth)
        if du.index == 0:
            reuse_source = collected[-1]

    # --- VIN plate ---
    deg = pick_degradation()
    img = image_gen.draw_plate(du.plate_vin_text, du.plate_condition, deg, rng, "NO. RANGKA")
    path = unit_dir / "intake_vin_plate.jpg"
    sha = image_gen.save_jpeg(img, path)
    register(
        path,
        sha,
        "INTAKE_VIN_PLATE",
        deg,
        {
            "kind": "vin_plate",
            "vin": du.plate_vin_text,
            "plate_condition": du.plate_condition,
            "confidence": {"vin": du.field_confidence.get("nomor_rangka", 0.95)},
        },
    )

    # --- engine number ---
    deg = pick_degradation()
    img = image_gen.draw_plate(du.plate_engine_text, "CLEAN", deg, rng, "NO. MESIN")
    path = unit_dir / "intake_engine_no.jpg"
    sha = image_gen.save_jpeg(img, path)
    register(
        path,
        sha,
        "INTAKE_ENGINE_NO",
        deg,
        {
            "kind": "engine_no",
            "engine_no": du.plate_engine_text,
            "confidence": {"engine_no": du.field_confidence.get("nomor_mesin", 0.95)},
        },
    )

    # --- odometer ---
    deg = pick_degradation()
    img = image_gen.draw_odometer(du.odometer_km, deg, rng)
    path = unit_dir / "intake_odometer.jpg"
    sha = image_gen.save_jpeg(img, path)
    register(
        path,
        sha,
        "INTAKE_ODOMETER",
        deg,
        {
            "kind": "odometer",
            "odometer_km": du.odometer_km,
            "confidence": {"odometer_km": du.field_confidence.get("odometer_km", 0.94)},
        },
    )

    # --- exterior set: all nine angles, with known damage labels ---
    for angle in image_gen.EXTERIOR_ANGLES:
        deg = pick_degradation()
        damages = image_gen.sample_damages(
            rng, angle, du.grade_label, du.celah_panel_present, du.rust_present, du.repaint_present
        )
        img = image_gen.draw_exterior(angle, du.colour, damages, deg, rng)
        path = unit_dir / f"{angle.lower()}.jpg"
        sha = image_gen.save_jpeg(img, path)
        register(
            path,
            sha,
            angle,
            deg,
            {
                "kind": "exterior",
                "angle": angle,
                "detections": [{k: v for k, v in d.items() if k != "bbox_px"} for d in damages],
            },
        )

    return reuse_source


def reset(session) -> None:
    """Truncate every seeded table.

    Uses TRUNCATE ... CASCADE with the append-only escape hatch enabled, which
    is the one legitimate reason to bypass the audit triggers. Refuses to run
    outside dev/ci - see `main`.
    """
    session.execute(text("SET LOCAL caready.allow_append_only_purge = 'on'"))
    tables = [
        "pii_access_log", "unit_status_transitions", "audit_log", "job_runs",
        "price_results", "pricing_model_versions", "residual_anchors",
        "auction_records", "otr_prices", "otr_price_snapshots",
        "damage_corrections", "damage_detections", "vision_inferences", "grades",
        "plate_condition_assessments", "vin_decode_results", "verification_queue",
        "cross_check_results", "ocr_extractions",
        "photo_upload_sessions", "photos",
        "non_visual_checklist_items", "unit_stnk_data",
        "variant_resolution_queue", "units",
        "catalog_curations", "vds_variant_map", "variant_aliases",
        "variants", "generations", "vehicle_models", "brands",
        "refresh_tokens", "users",
    ]
    session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    log("reset: all seeded tables truncated")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Caready with synthetic data")
    parser.add_argument("--reset", action="store_true", help="truncate seeded tables first")
    parser.add_argument("--no-images", action="store_true", help="skip image generation")
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment in ("prod", "staging"):
        print(
            f"REFUSING to seed synthetic data into environment '{settings.environment}'.\n"
            "Synthetic rows in a real database are indistinguishable from real ones "
            "to every downstream consumer.",
            file=sys.stderr,
        )
        return 2

    started = time.perf_counter()
    log(f"master seed = {MASTER_SEED} (output is deterministic)")
    log("ALL GENERATED DATA IS SYNTHETIC AND HAS NO REAL-WORLD VALIDITY")

    summary: dict[str, float] = {}
    with session_scope() as session:
        if args.reset:
            reset(session)

        if session.execute(select(Brand).limit(1)).first() is not None:
            log("catalog already present - nothing to do (use --reset to reseed)")
            return 0

        users = seed_users(session)
        variants = seed_catalog(session)
        otr_rows = seed_otr(session, variants)
        summary = seed_auctions(session, variants, otr_rows)
        seed_units(session, users, variants, with_images=not args.no_images)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "seed_summary.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "warning": (
                    "Synthetic data. Model output derived from it is not evidence "
                    "of pricing accuracy."
                ),
                "master_seed": MASTER_SEED,
                "generated_at": datetime.now(UTC).isoformat(),
                "auction_summary": summary,
                "demo_login_password": DEMO_PASSWORD,
                "demo_users": [u[0] for u in DEMO_USERS],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    log(f"done in {time.perf_counter() - started:.1f}s")
    log(f"demo login: {DEMO_USERS[0][0]} / {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
