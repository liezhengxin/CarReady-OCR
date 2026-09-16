"""Synthetic generator determinism and calibration.

Two things are being protected here:

  1. **Determinism.** The seeded defect cases (SYN-U-0000 ... SYN-U-0009) are
     referenced by unit code in the M2 acceptance tests. If the generator
     drifts, those tests start asserting against different units without
     failing in a way that points at the cause.

  2. **Calibration.** The bands documented in seed/README.md. A generator that
     silently drifts out of band changes what every downstream test is testing
     against - including, later, whether a pricing model is any good.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generators import auction as auction_gen  # noqa: E402
from generators import otr as otr_gen  # noqa: E402
from generators import units as unit_gen  # noqa: E402
from generators.catalog_spec import CATALOG, iter_variants, variant_count  # noqa: E402
from generators.common import (  # noqa: E402
    BRAND_SHARE,
    TARGET_AUCTION_ROWS,
    corrupt_tipe,
    stream,
    synthetic_vin,
)


@pytest.fixture(scope="module")
def otr_rows():
    return otr_gen.generate_otr_series()


@pytest.fixture(scope="module")
def auction_rows(otr_rows):
    return auction_gen.generate_auction_records(otr_gen.build_otr_lookup(otr_rows))


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_streams_are_reproducible() -> None:
    assert [stream("x").random() for _ in range(3)] == [stream("x").random() for _ in range(3)]


def test_streams_are_independent() -> None:
    """Adding a brand must not reshuffle the auction records. Independent
    streams are what make previously reviewed seed data stay valid."""
    assert stream("catalog").random() != stream("auction").random()


def test_otr_series_is_deterministic(otr_rows) -> None:
    again = otr_gen.generate_otr_series()
    assert len(again) == len(otr_rows)
    assert [r.price_idr for r in again[:200]] == [r.price_idr for r in otr_rows[:200]]


def test_auction_generation_is_deterministic(otr_rows, auction_rows) -> None:
    again = auction_gen.generate_auction_records(otr_gen.build_otr_lookup(otr_rows))
    assert len(again) == len(auction_rows)
    assert [r.external_ref for r in again[:500]] == [r.external_ref for r in auction_rows[:500]]
    assert [r.sale_price for r in again[:500]] == [r.sale_price for r in auction_rows[:500]]


def test_demo_units_are_deterministic() -> None:
    a, b = unit_gen.generate_demo_units(), unit_gen.generate_demo_units()
    assert [u.code for u in a] == [u.code for u in b]
    assert [u.nomor_rangka for u in a] == [u.nomor_rangka for u in b]


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


def test_catalog_has_meaningful_breadth() -> None:
    assert len(CATALOG) >= 10
    assert variant_count() >= 60


def test_every_catalog_brand_has_a_market_share() -> None:
    for brand in CATALOG:
        assert brand.name in BRAND_SHARE, f"{brand.name} has no share in BRAND_SHARE"


def test_variant_type_codes_are_unique() -> None:
    """The code is the join key between the catalog, the OTR series, and the
    auction records. A collision would silently merge two variants."""
    codes = [v.code for _, _, _, v in iter_variants()]
    assert len(codes) == len(set(codes))


def test_generation_year_ranges_are_valid() -> None:
    for _, _, generation, _ in iter_variants():
        if generation.year_end is not None:
            assert generation.year_end >= generation.year_start


def test_market_mix_is_mpv_heavy() -> None:
    """A sanity check on the sketch: the Indonesian used-auction population is
    dominated by low MPVs, not sedans."""
    body_types = [m.body_type for b in CATALOG for m in b.models]
    assert body_types.count("mpv") > body_types.count("sedan")


# --------------------------------------------------------------------------
# OTR series
# --------------------------------------------------------------------------


def test_otr_covers_every_variant(otr_rows) -> None:
    assert {r.code for r in otr_rows} == {v.code for _, _, _, v in iter_variants()}


def test_otr_prices_rise_over_time(otr_rows) -> None:
    """New-car list prices inflate. If this inverted, the residual ratio would
    drift in the wrong direction across the whole dataset."""
    by_code: dict[str, list] = {}
    for row in otr_rows:
        by_code.setdefault(row.code, []).append(row)
    for code, series in list(by_code.items())[:20]:
        series.sort(key=lambda r: r.effective_date)
        assert series[-1].price_idr > series[0].price_idr, f"{code} prices did not rise"


def test_otr_prices_are_quoted_in_whole_millions(otr_rows) -> None:
    assert all(int(r.price_idr) % 1_000_000 == 0 for r in otr_rows[:500])


def test_out_of_production_rows_are_labelled(otr_rows) -> None:
    """A stated simplification: the series continues past a generation's end so
    the residual ratio has a denominator. Those rows must be identifiable."""
    stale = [r for r in otr_rows if r.out_of_production]
    assert stale, "expected some out-of-production reference prices"
    assert all("reference" in r.raw_label for r in stale)


# --------------------------------------------------------------------------
# Auction calibration (the bands documented in seed/README.md)
# --------------------------------------------------------------------------


def test_row_count_is_in_the_briefed_range(auction_rows) -> None:
    assert 12_000 <= len(auction_rows) <= 20_000


def test_target_row_count_matches_the_brief() -> None:
    assert 12_000 <= TARGET_AUCTION_ROWS <= 20_000


def test_sold_share_is_calibrated(auction_rows) -> None:
    share = auction_gen.summarise(auction_rows)["sold_share"]
    assert 0.60 <= share <= 0.75, f"sold share {share:.3f} outside the documented band"


def test_unsold_units_exist_in_quantity(auction_rows) -> None:
    """Unsold units are left-censored observations and must be in the training
    set. Training only on sold units biases the model upward and inflates floor
    prices (§8.3)."""
    unsold = [r for r in auction_rows if r.outcome != "sold"]
    assert len(unsold) > 3_000


def test_no_bid_share_is_calibrated(auction_rows) -> None:
    share = auction_gen.summarise(auction_rows)["no_bid_share"]
    assert 0.06 <= share <= 0.16, f"no-bid share {share:.3f} outside the documented band"


def test_no_bid_and_below_reserve_are_distinguishable(auction_rows) -> None:
    """The distinction carries information: a lot that attracted bids but
    missed reserve locates true value far better than one nobody bid on."""
    no_bid = [r for r in auction_rows if r.outcome == "no_bid"]
    below = [r for r in auction_rows if r.outcome == "below_reserve"]
    assert all(r.highest_bid is None and r.bidder_count == 0 for r in no_bid)
    assert all(r.highest_bid is not None and r.bidder_count > 0 for r in below)


def test_median_residual_ratio_is_plausible(auction_rows) -> None:
    ratio = auction_gen.summarise(auction_rows)["median_residual_ratio"]
    assert 0.30 <= ratio <= 0.70, f"median residual ratio {ratio:.3f} outside the documented band"


def test_sold_rows_always_carry_a_price(auction_rows) -> None:
    assert all(r.sale_price is not None for r in auction_rows if r.outcome == "sold")


def test_unsold_rows_never_carry_a_sale_price(auction_rows) -> None:
    assert all(r.sale_price is None for r in auction_rows if r.outcome != "sold")


def test_every_row_has_a_reference_otr_price(auction_rows) -> None:
    """The residual anchor needs a denominator on every row."""
    assert all(r.otr_price_at_auction > 0 for r in auction_rows)


def test_older_units_are_cheaper_on_average(auction_rows) -> None:
    """Depreciation must be visible in the data, or the age feature is noise."""
    sold = [r for r in auction_rows if r.outcome == "sold" and not r.is_outlier and r.sale_price]
    young = [
        float(r.sale_price) / float(r.otr_price_at_auction)
        for r in sold
        if r.auction_date.year - r.model_year <= 3
    ]
    old = [
        float(r.sale_price) / float(r.otr_price_at_auction)
        for r in sold
        if r.auction_date.year - r.model_year >= 9
    ]
    assert young and old
    assert sum(young) / len(young) > sum(old) / len(old)


def test_worse_grades_fetch_less(auction_rows) -> None:
    """Condition must be a real signal, or the grading pipeline is decorative."""
    sold = [
        r for r in auction_rows
        if r.outcome == "sold" and not r.is_outlier and r.sale_price and r.grade_label
    ]
    by_grade: dict[str, list[float]] = {}
    for r in sold:
        by_grade.setdefault(r.grade_label, []).append(
            float(r.sale_price) / float(r.otr_price_at_auction)
        )
    means = {g: sum(v) / len(v) for g, v in by_grade.items()}
    assert means["A"] > means["C"] > means["E"]


# --------------------------------------------------------------------------
# Deliberate imperfections
# --------------------------------------------------------------------------


def test_imperfections_are_present_at_the_documented_rates(auction_rows) -> None:
    """Clean synthetic data produces a pipeline that has never met a real
    record. These must be present, or the normaliser and the outlier filter are
    never exercised."""
    s = auction_gen.summarise(auction_rows)
    assert 0.05 <= s["missing_odometer_share"] <= 0.14
    assert 0.03 <= s["missing_grade_share"] <= 0.12
    assert 0.25 <= s["missing_transmission_share"] <= 0.38
    assert 0.005 <= s["duplicate_share"] <= 0.03
    assert 0.001 <= s["outlier_share"] <= 0.02


def test_tipe_strings_are_inconsistent(auction_rows) -> None:
    """The same variant must arrive spelled several ways - that is the catalog
    matcher's actual job (§6.1)."""
    by_code: dict[str, set[str]] = {}
    for row in auction_rows:
        by_code.setdefault(row.variant_code, set()).add(row.raw_tipe)
    multi = [code for code, variants in by_code.items() if len(variants) > 3]
    assert len(multi) > 20, "expected many variants with several raw spellings"


def test_tipe_corruption_covers_distinct_shapes() -> None:
    rng = stream("test-corrupt")
    results = {corrupt_tipe(rng, "Avanza G", "F653RM-GMQFJJ") for _ in range(200)}
    assert len(results) >= 8


def test_duplicates_point_at_their_original(auction_rows) -> None:
    """Duplicates are flagged, never deleted - deleting them destroys the
    evidence that a duplicate existed."""
    dups = [r for r in auction_rows if r.is_duplicate_of]
    assert dups
    refs = {r.external_ref for r in auction_rows}
    assert all(d.is_duplicate_of in refs for d in dups)


# --------------------------------------------------------------------------
# Demo units and seeded defect cases
# --------------------------------------------------------------------------


def test_every_declared_defect_case_is_generated() -> None:
    units = {u.code: u for u in unit_gen.generate_demo_units()}
    for index, case in unit_gen.DEFECT_CASES.items():
        code = f"SYN-U-{index:04d}"
        assert code in units, f"{code} missing"
        assert units[code].defect_case == case


def test_vin_mismatch_case_actually_differs() -> None:
    unit = unit_gen.generate_demo_units()[0]
    assert unit.defect_case == "vin_mismatch"
    assert unit.plate_vin_text != unit.nomor_rangka


def test_vin_near_match_differs_by_exactly_one_character() -> None:
    unit = unit_gen.generate_demo_units()[1]
    assert unit.defect_case == "vin_near_match"
    assert len(unit.plate_vin_text) == len(unit.nomor_rangka)
    diffs = sum(1 for a, b in zip(unit.plate_vin_text, unit.nomor_rangka, strict=True) if a != b)
    assert diffs == 1, "must fall inside the fuzzy threshold of 2"


def test_ocr_ambiguity_case_matches_only_after_normalisation() -> None:
    """ISO 3779 excludes I, O and Q precisely because they are confusable with
    1 and 0. This case must resolve to PASS - with normalisation_applied
    recorded, so it stays distinguishable from an exact match."""
    unit = unit_gen.generate_demo_units()[2]
    assert unit.defect_case == "vin_ocr_ambiguity"
    assert unit.plate_vin_text != unit.nomor_rangka, "should differ before normalisation"
    normalise = str.maketrans({"O": "0", "I": "1", "Q": "0"})
    assert unit.plate_vin_text.translate(normalise) == unit.nomor_rangka.translate(normalise)


def test_tampered_plate_case_is_classified_as_tampered() -> None:
    unit = unit_gen.generate_demo_units()[4]
    assert unit.plate_condition == "TAMPERED_SUSPECTED"


def test_odometer_rollback_case_trips_the_hard_flag() -> None:
    """config/crosschecks.yaml escalates below 1,000 km/yr on a 5+ year unit to
    BLOCKER - the classic tampering profile."""
    unit = unit_gen.generate_demo_units()[5]
    age = 2026 - unit.model_year
    assert age >= 5
    assert unit.odometer_km / age < 2000


def test_unresolved_variant_case_matches_no_catalog_code() -> None:
    unit = unit_gen.generate_demo_units()[8]
    assert unit.tipe not in {v.code for _, _, _, v in iter_variants()}


def test_low_confidence_case_falls_below_the_thresholds() -> None:
    unit = unit_gen.generate_demo_units()[9]
    assert unit.field_confidence["nomor_rangka"] < 0.92
    assert unit.field_confidence["tahun_pembuatan"] < 0.90
    assert unit.field_confidence["odometer_km"] < 0.90


def test_every_unit_answers_the_whole_non_visual_checklist() -> None:
    """A partially answered checklist is not a gate (§8.4)."""
    expected = {
        "flood_indication", "chassis_repair", "engine_condition",
        "transmission_condition", "odometer_tampering", "airbag_deployed",
        "document_completeness",
    }
    for unit in unit_gen.generate_demo_units():
        assert set(unit.checklist) == expected


def test_flagged_checklist_items_always_carry_a_note() -> None:
    """A flag without a note is not actionable, and the database CHECK
    constraint rejects it."""
    for unit in unit_gen.generate_demo_units():
        for item, answer in unit.checklist.items():
            if answer == "flagged":
                assert unit.checklist_notes.get(item), f"{unit.code}/{item} flagged without a note"


def test_synthetic_vins_avoid_the_iso_excluded_letters() -> None:
    rng = stream("test-vin")
    for _ in range(200):
        vin = synthetic_vin(rng, "MHF")
        assert len(vin) == 17
        assert not set(vin[3:]) & set("IOQ")
