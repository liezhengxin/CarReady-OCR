"""Historical auction record generator (§9).

SYNTHETIC. Every row is fabricated. See seed/README.md for the full statement
of the generative process and why model output from this data proves nothing.

Generative process
------------------
For one record:

  1. Pick a variant by brand share x model share, and a model year weighted
     toward recent-but-not-new units (the lease-return profile).
  2. otr_at_auction  <- the OTR series at the auction date.
  3. Deterministic value:

         value = otr * A * exp(-k * age)
                     * odometer_effect
                     * condition_effect
                     * location_effect
                     * seller_effect
                     * market_index(t)
                 - tax_penalty

     A (0.82) folds together the immediate new-to-used drop and the discount
     an auction clears at relative to retail. k is the model's annual
     depreciation constant from the catalog spec.

  4. Bidding outcome:
         demand   = value * LogNormal(0, sigma)
         reserve  = value * Normal(mu_reserve, sd_reserve)     [seller's belief]
         bidders  ~ Poisson(lambda(desirability))

         bidders == 0            -> NO_BID
         demand  >= reserve      -> SOLD at a price between reserve and demand
         otherwise               -> BELOW_RESERVE, highest_bid = demand

     This produces the left-censored unsold rows §8.3 requires. Unsold units
     are NOT a defect in the data - a model trained only on sold units is
     biased upward, which is the exact failure this system exists to prevent.

  5. Imperfections are then injected at the rates in common.ImperfectionRates:
     missing odometer, inconsistent `tipe` strings, duplicates, outlier prices,
     missing grade, missing transmission.

Calibration targets (asserted by tests):
    sold share            0.60 - 0.75
    no-bid share          0.06 - 0.16
    median residual ratio 0.30 - 0.70
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from .catalog_spec import BrandSpec, GenerationSpec, ModelSpec, VariantSpec, iter_variants
from .common import (
    BRANCHES,
    BRAND_SHARE,
    COLOUR_SHARE,
    GRADE_SCORE_RANGE,
    GRADE_SHARE,
    HISTORY_END,
    HISTORY_START,
    RATES,
    SELLER_TYPE_SHARE,
    TARGET_AUCTION_ROWS,
    corrupt_tipe,
    random_date,
    stream,
    weighted_choice,
)
from .otr import otr_as_of

# --- value model constants -------------------------------------------------
#: New-to-auction level: immediate depreciation plus the auction discount.
AUCTION_LEVEL = 0.82
#: Assumed annual mileage used as the odometer baseline.
EXPECTED_KM_PER_YEAR = 15_000
#: Sensitivity of value to mileage deviation from baseline, and its clamps.
ODOMETER_SENSITIVITY = 0.12
ODOMETER_EFFECT_FLOOR = 0.78
ODOMETER_EFFECT_CEIL = 1.12
#: Value lost per damage point, and the floor it saturates at.
DAMAGE_SENSITIVITY = 0.0045
DAMAGE_EFFECT_FLOOR = 0.55
#: Bidding noise and reserve-setting error.
DEMAND_SIGMA = 0.075
RESERVE_MEAN = 0.94
RESERVE_SD = 0.10
#: Tuned so the sold share lands in the calibration band above.
SELLER_EFFECT = {"leasing": 0.975, "fleet": 0.985, "dealer": 1.010, "individual": 1.020}
#: Colours outside the common set carry a small penalty.
UNCOMMON_COLOUR_EFFECT = 0.975
COMMON_COLOUR_THRESHOLD = 0.06
#: Flat rupiah penalties for tax status, mirroring deduction_coldstart.yaml.
TAX_PENALTY_IDR = {
    "ACTIVE": 0,
    "EXPIRING_SOON": 0,
    "EXPIRED_LT_12M": 1_500_000,
    "EXPIRED_GTE_12M": 4_500_000,
}
TAX_STATUS_SHARE = {
    "ACTIVE": 0.72,
    "EXPIRING_SOON": 0.11,
    "EXPIRED_LT_12M": 0.12,
    "EXPIRED_GTE_12M": 0.05,
}


@dataclass
class AuctionRow:
    external_ref: str
    brand: str
    model: str
    generation: str
    variant_code: str
    raw_merk: str
    raw_tipe: str
    raw_model: str
    model_year: int
    transmission: str | None
    odometer_km: int | None
    colour: str | None
    engine_cc: int
    grade_label: str | None
    damage_score: float | None
    celah_panel_present: bool
    rust_present: bool
    repaint_present: bool
    tax_status: str
    auction_date: date
    auction_location: str
    seller_type: str
    outcome: str
    sale_price: Decimal | None
    reserve_price: Decimal
    highest_bid: Decimal | None
    bidder_count: int
    otr_price_at_auction: Decimal
    is_duplicate_of: str | None = None
    is_outlier: bool = False


def market_index(when: date) -> float:
    """Slow market drift plus an annual seasonal cycle.

    The seasonal term stands in for the pre-Lebaran demand bump and the
    post-holiday slump. It exists so the `auction_month` and `market_index`
    features in §8.1 have something real to pick up, rather than being noise
    the model must learn to ignore.
    """
    t = (when - HISTORY_START).days / 365.25
    trend = 1.0 + 0.018 * t
    seasonal = 1.0 + 0.022 * math.sin(2 * math.pi * (when.timetuple().tm_yday / 365.25) - 0.9)
    return trend * seasonal


def _pick_model_year(rng, generation: GenerationSpec, auction_year: int) -> int:
    """Weight toward 3-7 year old units - the lease-return profile that
    dominates this channel."""
    lo = generation.year_start
    hi = min(generation.year_end or auction_year, auction_year)
    if hi < lo:
        hi = lo
    years = list(range(lo, hi + 1))
    weights = []
    for y in years:
        age = auction_year - y
        # Triangular-ish peak at age 5.
        weights.append(math.exp(-((age - 5) ** 2) / 18.0) + 0.05)
    return rng.choices(years, weights=weights, k=1)[0]


def _condition(rng) -> tuple[str, float, bool, bool, bool]:
    grade = weighted_choice(rng, GRADE_SHARE)
    lo, hi = GRADE_SCORE_RANGE[grade]
    score = rng.uniform(lo, hi)
    # Structural signals cluster in the worse grades, which is what makes
    # `celah_panel_present` informative beyond the grade label itself.
    celah = rng.random() < {"A": 0.01, "B": 0.05, "C": 0.16, "D": 0.34, "E": 0.55}[grade]
    rust = rng.random() < {"A": 0.01, "B": 0.04, "C": 0.12, "D": 0.28, "E": 0.48}[grade]
    repaint = rng.random() < {"A": 0.03, "B": 0.12, "C": 0.30, "D": 0.48, "E": 0.62}[grade]
    return grade, round(score, 2), celah, rust, repaint


def _build_variant_pool() -> list[tuple[BrandSpec, ModelSpec, GenerationSpec, VariantSpec, float]]:
    """Flatten the catalog into a weighted sampling pool."""
    pool = []
    for brand, model, generation, variant in iter_variants():
        brand_w = BRAND_SHARE.get(brand.name, 0.01)
        # Split the model's share evenly across its generations and variants;
        # the catalog does not carry per-variant volume and inventing one
        # would be false precision.
        n_variants = len(generation.variants)
        n_generations = len(model.generations)
        weight = brand_w * model.share / (n_generations * n_variants)
        pool.append((brand, model, generation, variant, weight))
    return pool


def generate_auction_records(otr_lookup: dict[str, list[tuple[date, Decimal]]]) -> list[AuctionRow]:
    rng = stream("auction")
    pool = _build_variant_pool()
    weights = [entry[4] for entry in pool]

    common_colours = {c for c, share in COLOUR_SHARE.items() if share >= COMMON_COLOUR_THRESHOLD}
    rows: list[AuctionRow] = []

    for i in range(TARGET_AUCTION_ROWS):
        brand, model, generation, variant, _ = rng.choices(pool, weights=weights, k=1)[0]
        auction_date = random_date(rng, HISTORY_START, HISTORY_END)
        model_year = _pick_model_year(rng, generation, auction_date.year)
        age = max(0.25, (auction_date - date(model_year, 6, 30)).days / 365.25)

        otr = otr_as_of(otr_lookup, variant.code, auction_date)

        # --- odometer ---
        expected_km = EXPECTED_KM_PER_YEAR * age
        odometer = max(500, int(rng.gauss(expected_km, expected_km * 0.32)))
        odo_ratio = odometer / max(expected_km, 1.0)
        odo_effect = min(
            ODOMETER_EFFECT_CEIL,
            max(ODOMETER_EFFECT_FLOOR, 1.0 - ODOMETER_SENSITIVITY * (odo_ratio - 1.0)),
        )

        # --- condition ---
        grade, damage_score, celah, rust, repaint = _condition(rng)
        condition_effect = max(DAMAGE_EFFECT_FLOOR, 1.0 - DAMAGE_SENSITIVITY * damage_score)
        # Panel gap costs more than its damage-score contribution alone, which
        # is the asymmetry §7.2 calls out.
        if celah:
            condition_effect *= 0.955

        branch = weighted_choice(rng, {k: v["share"] for k, v in BRANCHES.items()})
        location_effect = BRANCHES[branch]["price_effect"]
        seller = weighted_choice(rng, SELLER_TYPE_SHARE)
        colour = weighted_choice(rng, COLOUR_SHARE)
        colour_effect = 1.0 if colour in common_colours else UNCOMMON_COLOUR_EFFECT
        tax_status = weighted_choice(rng, TAX_STATUS_SHARE)

        value = (
            float(otr)
            * AUCTION_LEVEL
            * math.exp(-model.depreciation_k * age)
            * variant.residual_modifier
            * odo_effect
            * condition_effect
            * location_effect
            * SELLER_EFFECT[seller]
            * colour_effect
            * market_index(auction_date)
        )
        value = max(5_000_000.0, value - TAX_PENALTY_IDR[tax_status])

        # --- bidding ---
        demand = value * math.exp(rng.gauss(0.0, DEMAND_SIGMA))
        reserve = value * max(0.55, rng.gauss(RESERVE_MEAN, RESERVE_SD))
        # Desirability drives turnout: popular, newer, cleaner units draw more
        # bidders. A unit with no bidders is a different observation from one
        # that attracted bids but missed reserve.
        desirability = (
            2.6
            * BRAND_SHARE.get(brand.name, 0.02)
            / 0.12
            * (1.25 if grade in ("A", "B") else 0.85 if grade == "C" else 0.5)
            * (1.2 if age < 6 else 0.8)
        )
        bidders = min(24, _poisson(rng, max(0.15, desirability)))

        if bidders == 0:
            outcome, sale_price, highest_bid = "no_bid", None, None
        elif demand >= reserve:
            outcome = "sold"
            # Clears somewhere between the reserve and the top of demand.
            sale_price = Decimal(int(round(reserve + (demand - reserve) * rng.uniform(0.25, 1.0))))
            highest_bid = sale_price
        else:
            outcome = "below_reserve"
            sale_price = None
            highest_bid = Decimal(int(round(demand)))

        raw_tipe = (
            corrupt_tipe(rng, f"{model.name} {variant.trim}", variant.code)
            if rng.random() < RATES.inconsistent_tipe
            else f"{model.name} {variant.trim}"
        )

        row = AuctionRow(
            external_ref=f"SYN-{i:06d}",
            brand=brand.name,
            model=model.name,
            generation=generation.name,
            variant_code=variant.code,
            raw_merk=brand.name.upper() if rng.random() < 0.3 else brand.name,
            raw_tipe=raw_tipe,
            raw_model=model.name,
            model_year=model_year,
            transmission=None if rng.random() < RATES.missing_transmission else variant.transmission,
            odometer_km=None if rng.random() < RATES.missing_odometer else odometer,
            colour=None if rng.random() < RATES.dirty_colour else colour,
            engine_cc=variant.engine_cc,
            grade_label=None if rng.random() < RATES.missing_grade else grade,
            damage_score=None if rng.random() < RATES.missing_grade else damage_score,
            celah_panel_present=celah,
            rust_present=rust,
            repaint_present=repaint,
            tax_status=tax_status,
            auction_date=auction_date,
            auction_location=branch,
            seller_type=seller,
            outcome=outcome,
            sale_price=sale_price,
            reserve_price=Decimal(int(round(reserve))),
            highest_bid=highest_bid,
            bidder_count=bidders,
            otr_price_at_auction=otr,
        )
        rows.append(row)

    rows = _inject_outliers(rng, rows)
    rows = _inject_duplicates(rng, rows)
    return rows


def _poisson(rng, lam: float) -> int:
    """Knuth's method. Sufficient for the small lambdas here and keeps the
    generator dependent only on `random`, so it stays reproducible without
    pinning a numpy version."""
    target = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= target:
            return k
        k += 1
        if k > 200:  # pragma: no cover - guards a pathological lambda
            return k


def _inject_outliers(rng, rows: list[AuctionRow]) -> list[AuctionRow]:
    """Data-entry slips: a price off by an order of magnitude, or a digit.

    Left in the data deliberately. The training pipeline has to detect and
    exclude these; a dataset with none of them would let a fragile pipeline
    look robust.
    """
    for idx, row in enumerate(rows):
        if row.outcome != "sold" or row.sale_price is None:
            continue
        if rng.random() >= RATES.outlier_price:
            continue
        factor = rng.choice([0.1, 0.01, 10.0, 100.0])
        rows[idx] = replace(row, sale_price=Decimal(int(row.sale_price * Decimal(str(factor)))), is_outlier=True)
    return rows


def _inject_duplicates(rng, rows: list[AuctionRow]) -> list[AuctionRow]:
    """Near-duplicate records, as produced by a double-entered import.

    Some are byte-identical apart from the reference; others differ in one
    field, which is the harder case for a naive dedupe.
    """
    extra: list[AuctionRow] = []
    for row in rows:
        if rng.random() >= RATES.duplicate_record:
            continue
        clone = replace(
            row,
            external_ref=f"{row.external_ref}-DUP",
            is_duplicate_of=row.external_ref,
        )
        if rng.random() < 0.5 and clone.odometer_km is not None:
            clone = replace(clone, odometer_km=clone.odometer_km + rng.randint(1, 50))
        extra.append(clone)
    return rows + extra


def summarise(rows: list[AuctionRow]) -> dict[str, float]:
    """Calibration summary. Printed by the seeder and asserted by tests."""
    total = len(rows)
    sold = [r for r in rows if r.outcome == "sold" and not r.is_outlier]
    no_bid = [r for r in rows if r.outcome == "no_bid"]
    below = [r for r in rows if r.outcome == "below_reserve"]
    ratios = sorted(
        float(r.sale_price) / float(r.otr_price_at_auction) for r in sold if r.sale_price is not None
    )
    return {
        "total_rows": total,
        "sold_share": len(sold) / total,
        "no_bid_share": len(no_bid) / total,
        "below_reserve_share": len(below) / total,
        "median_residual_ratio": ratios[len(ratios) // 2] if ratios else 0.0,
        "missing_odometer_share": sum(1 for r in rows if r.odometer_km is None) / total,
        "missing_grade_share": sum(1 for r in rows if r.grade_label is None) / total,
        "missing_transmission_share": sum(1 for r in rows if r.transmission is None) / total,
        "duplicate_share": sum(1 for r in rows if r.is_duplicate_of) / total,
        "outlier_share": sum(1 for r in rows if r.is_outlier) / total,
    }
