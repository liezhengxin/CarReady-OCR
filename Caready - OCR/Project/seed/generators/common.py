"""Shared primitives for the synthetic data generators.

EVERYTHING THIS PACKAGE PRODUCES IS FABRICATED. No row, image, or price here
derives from a real vehicle, a real auction, or a real person. Output must
never be presented as evidence of pricing accuracy (§0.6) and every generated
row is written with `is_synthetic = True`.

Determinism: one master seed drives every stream. Re-running the generators
with the same seed produces byte-identical output, which is what makes the
seeded cross-check test cases (§5.4) reliable rather than flaky.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date, timedelta

#: Master seed. Change it and every downstream stream changes together.
MASTER_SEED = 20260101

#: The simulated history window. Three years of auctions ending "today" in
#: the generated world, so age and market-index features have room to move.
HISTORY_END = date(2026, 9, 1)
HISTORY_YEARS = 3
HISTORY_START = HISTORY_END - timedelta(days=365 * HISTORY_YEARS)

#: Target row count for `auction_records` (§9 asks for 12,000-20,000).
TARGET_AUCTION_ROWS = 16_000


def stream(name: str) -> random.Random:
    """An independent, reproducible RNG per named stream.

    Separate streams matter: if catalog generation and auction generation
    shared one RNG, adding a single brand would reshuffle every auction row
    and invalidate previously reviewed seed data. Deriving each stream's seed
    from the name keeps them independent.
    """
    digest = hashlib.sha256(f"{MASTER_SEED}:{name}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


# --------------------------------------------------------------------------
# Indonesian market mix
# --------------------------------------------------------------------------
# Shares are a plausible sketch of the Indonesian used-auction population -
# MPV-heavy, Toyota/Daihatsu-dominant, with LCGC and commercial tails. They
# are NOT measured market data; they exist so the generated distribution is
# not uniform, which would make every model look better than it is.
# --------------------------------------------------------------------------

BRAND_SHARE: dict[str, float] = {
    "Toyota": 0.29,
    "Daihatsu": 0.17,
    "Honda": 0.13,
    "Mitsubishi": 0.12,
    "Suzuki": 0.10,
    "Nissan": 0.05,
    "Wuling": 0.04,
    "Isuzu": 0.04,
    "Hyundai": 0.03,
    "Mazda": 0.02,
    "Kia": 0.01,
}

#: Auction branches. Volume is concentrated in Jabodetabek, with regional
#: branches carrying a location price effect.
BRANCHES: dict[str, dict[str, float]] = {
    "JKT-01": {"share": 0.26, "price_effect": 1.000},
    "JKT-02": {"share": 0.14, "price_effect": 0.995},
    "BDG-01": {"share": 0.11, "price_effect": 0.985},
    "SBY-01": {"share": 0.15, "price_effect": 0.978},
    "SMG-01": {"share": 0.08, "price_effect": 0.972},
    "MDN-01": {"share": 0.09, "price_effect": 0.960},
    "MKS-01": {"share": 0.07, "price_effect": 0.955},
    "BPP-01": {"share": 0.06, "price_effect": 0.948},
    "DPS-01": {"share": 0.04, "price_effect": 0.990},
}

SELLER_TYPE_SHARE: dict[str, float] = {
    "leasing": 0.58,
    "fleet": 0.17,
    "dealer": 0.15,
    "individual": 0.10,
}

#: Colour popularity. The "common colour" flag in the pricing features is
#: derived from these shares, so the two stay consistent.
COLOUR_SHARE: dict[str, float] = {
    "Hitam": 0.25,
    "Putih": 0.24,
    "Silver": 0.15,
    "Abu-abu": 0.11,
    "Merah": 0.07,
    "Biru": 0.06,
    "Coklat": 0.04,
    "Champagne": 0.03,
    "Hijau": 0.02,
    "Kuning": 0.015,
    "Orange": 0.015,
    "Ungu": 0.005,
}

#: Grade mix under the PLACEHOLDER rubric in config/grading.yaml. Skewed toward
#: B/C because a lease-return population is mostly serviceable but used.
GRADE_SHARE: dict[str, float] = {"A": 0.08, "B": 0.34, "C": 0.38, "D": 0.16, "E": 0.04}

#: Representative damage-score midpoints per grade band, used to give each
#: generated unit a score consistent with its label.
GRADE_SCORE_RANGE: dict[str, tuple[float, float]] = {
    "A": (0.0, 15.0),
    "B": (15.0, 35.0),
    "C": (35.0, 60.0),
    "D": (60.0, 90.0),
    "E": (90.0, 150.0),
}


def weighted_choice(rng: random.Random, weights: dict[str, float]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


# --------------------------------------------------------------------------
# Deliberate imperfections (§9)
# --------------------------------------------------------------------------
# Clean synthetic data produces a pipeline that has never met a real record.
# These rates inject the specific failures the system must survive.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ImperfectionRates:
    #: Odometer absent entirely. Common in legacy auction exports.
    missing_odometer: float = 0.09
    #: `tipe` written inconsistently - the catalog normaliser's real job.
    inconsistent_tipe: float = 0.22
    #: Whole record duplicated, sometimes with a small field difference.
    duplicate_record: float = 0.012
    #: Price far outside the plausible band - a data-entry slip.
    outlier_price: float = 0.006
    #: Grade missing, because the unit predates graded intake.
    missing_grade: float = 0.07
    #: Colour missing or free-text nonsense.
    dirty_colour: float = 0.04
    #: Transmission unrecorded - the systematic gap the catalog exists to fill.
    missing_transmission: float = 0.31


RATES = ImperfectionRates()


#: Ways the same variant gets written in a source system. The catalog matcher
#: (§6.1) has to collapse these onto one entry; if it cannot, pricing inherits
#: a directional error.
TIPE_CORRUPTIONS: tuple[str, ...] = (
    "{tipe}",
    "{tipe} A/T",
    "{tipe} M/T",
    "{tipe}  ",
    " {tipe}",
    "{tipe_lower}",
    "{tipe_nospace}",
    "{tipe}-{code}",
    "{code}",
    "{tipe} NEW",
    "ALL NEW {tipe}",
    "{tipe} 1.5",
    "{tipe}/{code}",
)


def corrupt_tipe(rng: random.Random, tipe: str, code: str) -> str:
    """Render a variant's `tipe` the way a careless source system would."""
    template = rng.choice(TIPE_CORRUPTIONS)
    return template.format(
        tipe=tipe,
        tipe_lower=tipe.lower(),
        tipe_nospace=tipe.replace(" ", ""),
        code=code,
    )


# --------------------------------------------------------------------------
# Synthetic identifiers
# --------------------------------------------------------------------------


VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"  # ISO 3779: no I, O, Q
PLATE_PREFIXES = ("B", "D", "F", "L", "N", "AB", "AD", "BK", "DK", "KT", "H", "T")
PLATE_SUFFIX_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def synthetic_vin(rng: random.Random, wmi: str) -> str:
    """A 17-character VIN-shaped string.

    Shaped like a VIN so the parsing and normalisation code paths are
    exercised. It decodes to nothing real.
    """
    body = "".join(rng.choice(VIN_ALPHABET) for _ in range(14))
    return f"{wmi}{body}"


def synthetic_engine_no(rng: random.Random, prefix: str) -> str:
    return f"{prefix}{rng.randint(100000, 999999)}"


def synthetic_plate(rng: random.Random) -> str:
    prefix = rng.choice(PLATE_PREFIXES)
    number = rng.randint(1, 9999)
    suffix = "".join(rng.choice(PLATE_SUFFIX_LETTERS) for _ in range(rng.choice([2, 3])))
    return f"{prefix} {number} {suffix}"


#: Fabricated owner names. Common Indonesian given/family names combined at
#: random - any resemblance to a real person is coincidental, and these rows
#: are PII-classified and encrypted exactly as real ones would be, so the PDP
#: code paths are exercised.
GIVEN_NAMES = (
    "Budi", "Siti", "Agus", "Dewi", "Eko", "Rina", "Andi", "Sri", "Joko", "Ani",
    "Hendra", "Maya", "Rudi", "Fitri", "Bambang", "Lestari", "Dian", "Wahyu",
    "Putri", "Arif", "Nurul", "Yanto", "Indah", "Fajar", "Ratna",
)
FAMILY_NAMES = (
    "Santoso", "Wijaya", "Pratama", "Kusuma", "Halim", "Setiawan", "Nugroho",
    "Hartono", "Saputra", "Maulana", "Rahman", "Permana", "Gunawan", "Susanto",
    "Firmansyah", "Cahyono", "Wibowo", "Utami", "Hidayat", "Salim",
)
STREET_NAMES = (
    "Jl. Melati", "Jl. Anggrek", "Jl. Kenanga", "Jl. Merdeka", "Jl. Diponegoro",
    "Jl. Sudirman", "Jl. Gatot Subroto", "Jl. Ahmad Yani", "Jl. Cendrawasih",
    "Jl. Mawar", "Jl. Kartini", "Jl. Pahlawan",
)
CITIES = (
    ("Jakarta Selatan", "DKI Jakarta"), ("Bekasi", "Jawa Barat"),
    ("Bandung", "Jawa Barat"), ("Surabaya", "Jawa Timur"),
    ("Semarang", "Jawa Tengah"), ("Medan", "Sumatera Utara"),
    ("Makassar", "Sulawesi Selatan"), ("Denpasar", "Bali"),
    ("Tangerang", "Banten"), ("Balikpapan", "Kalimantan Timur"),
)


def synthetic_name(rng: random.Random) -> str:
    return f"{rng.choice(GIVEN_NAMES)} {rng.choice(FAMILY_NAMES)}"


def synthetic_address(rng: random.Random) -> str:
    city, province = rng.choice(CITIES)
    return (
        f"{rng.choice(STREET_NAMES)} No. {rng.randint(1, 180)} "
        f"RT {rng.randint(1, 15):02d}/RW {rng.randint(1, 12):02d}, {city}, {province}"
    )


def random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))
