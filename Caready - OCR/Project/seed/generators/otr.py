"""New-car OTR price series generator (§9).

Generative process
------------------
For each catalog variant a quarterly price series is produced across the
history window plus one year of lead-in:

    otr(t) = base_otr * (1 + annual_inflation) ** (t - BASE_OTR_YEAR)
             * brand_drift(brand, t)
             * quantise_to_million(...)

`annual_inflation` is drawn once per variant from a narrow band, so different
models drift apart slowly rather than moving in lockstep - which is what makes
the residual-value anchor do any work.

A deliberate simplification, stated plainly: the series continues for variants
that are out of production. A residual ratio needs a denominator at the
auction date, and the conventional denominator in residual-value work is the
current new price of the nearest equivalent. Rows generated past a
generation's `year_end` carry `out_of_production = True` so downstream code can
treat them as reference prices rather than quotes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .catalog_spec import BASE_OTR_YEAR, iter_variants
from .common import HISTORY_END, HISTORY_START, stream

#: Quarterly. Monthly would be false precision - manufacturer list prices in
#: this market move a few times a year, not continuously.
QUARTER_MONTHS = (1, 4, 7, 10)

#: Annual list-price inflation band. Indonesian new-car prices have moved in
#: this broad range over recent years; the exact figure is unimportant, the
#: point is that it is positive and variant-specific.
INFLATION_MIN = 0.032
INFLATION_MAX = 0.071

#: Prices are quoted in whole millions of rupiah, as they are in the market.
PRICE_QUANTUM = 1_000_000


@dataclass(frozen=True)
class OtrRow:
    brand: str
    model: str
    generation: str
    trim: str
    transmission: str
    code: str
    effective_date: date
    price_idr: Decimal
    out_of_production: bool
    raw_label: str


def _quarters(start: date, end: date) -> list[date]:
    out: list[date] = []
    year = start.year
    while year <= end.year:
        for month in QUARTER_MONTHS:
            d = date(year, month, 1)
            if start <= d <= end:
                out.append(d)
        year += 1
    return out


def generate_otr_series() -> list[OtrRow]:
    rng = stream("otr")
    # One year of lead-in so an auction on day one of the window still has a
    # preceding price point to interpolate from.
    start = date(HISTORY_START.year - 1, 1, 1)
    quarters = _quarters(start, HISTORY_END)

    rows: list[OtrRow] = []
    for brand, model, generation, variant in iter_variants():
        inflation = rng.uniform(INFLATION_MIN, INFLATION_MAX)
        # A small persistent brand-level offset, so brands are not identical
        # once inflation is stripped out.
        brand_drift = rng.uniform(0.985, 1.015)

        for q in quarters:
            years_from_base = (q.year + (q.month - 1) / 12) - BASE_OTR_YEAR
            raw = variant.base_otr * ((1 + inflation) ** years_from_base) * brand_drift
            price = Decimal(int(round(raw / PRICE_QUANTUM)) * PRICE_QUANTUM)

            out_of_production = generation.year_end is not None and q.year > generation.year_end
            label = f"{brand.name} {model.name} {variant.trim} {variant.transmission}"
            rows.append(
                OtrRow(
                    brand=brand.name,
                    model=model.name,
                    generation=generation.name,
                    trim=variant.trim,
                    transmission=variant.transmission,
                    code=variant.code,
                    effective_date=q,
                    price_idr=price,
                    out_of_production=out_of_production,
                    raw_label=label + (" (reference, out of production)" if out_of_production else ""),
                )
            )
    return rows


def build_otr_lookup(rows: list[OtrRow]) -> dict[str, list[tuple[date, Decimal]]]:
    """Index the series by variant code for fast as-of lookup during auction
    generation."""
    lookup: dict[str, list[tuple[date, Decimal]]] = {}
    for row in rows:
        lookup.setdefault(row.code, []).append((row.effective_date, row.price_idr))
    for series in lookup.values():
        series.sort(key=lambda pair: pair[0])
    return lookup


def otr_as_of(lookup: dict[str, list[tuple[date, Decimal]]], code: str, when: date) -> Decimal:
    """Most recent price at or before `when`; the earliest point if `when`
    precedes the series."""
    series = lookup[code]
    chosen = series[0][1]
    for effective, price in series:
        if effective > when:
            break
        chosen = price
    return chosen
