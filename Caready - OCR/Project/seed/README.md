# Synthetic seed data

> **All data produced by this package is fabricated.**
>
> No row, image, price, or person here derives from a real vehicle, a real
> auction, or a real individual. Any model trained on it is recorded with
> `trained_on_synthetic = True`, every generated report carries a header
> stating the same, and the API serves a non-dismissible warning banner while
> `SYNTHETIC_DATA_MODE` is enabled.
>
> **Model output derived from this data is not evidence of pricing accuracy.**
> It demonstrates that the pipeline runs end to end. Nothing more can be
> claimed from it, and nothing more should be.

## Running

```bash
python seed/run_seed.py                # full seed, ~16k auction rows + imagery
python seed/run_seed.py --no-images    # skip imagery (much faster)
python seed/run_seed.py --reset        # truncate seeded tables first
```

The seeder refuses to run when `ENVIRONMENT` is `prod` or `staging`. Synthetic
rows in a real database are indistinguishable from real ones to every
downstream consumer, so the guard is a hard exit rather than a prompt.

Demo accounts (password `caready-dev-2026`):

| Email | Role |
|---|---|
| `inspektur@caready.local` | inspector |
| `penilai@caready.local` | appraiser |
| `penyetuju@caready.local` | approver |
| `admin@caready.local` | admin |

## Determinism

One master seed (`MASTER_SEED = 20260101`) drives every stream. Each generator
derives its own RNG from `sha256(master_seed:stream_name)`, so streams are
independent: adding a brand to the catalog does not reshuffle the auction
records, and the seeded defect cases stay at fixed unit codes across runs.

Re-running with the same seed produces identical output.

## What gets generated

| Artefact | Volume | Module |
|---|---|---|
| Users | 5 | `run_seed.py` |
| Catalog (brands → variants) | 11 brands, ~110 variants | `catalog_spec.py` |
| New-car OTR price series | quarterly × 4 years × all variants | `otr.py` |
| Historical auction records | 16,000 (+ duplicates) | `auction.py` |
| Demo units | 40, with full capture sets | `units.py` |
| Document & vehicle imagery | 13 images per unit | `images.py` |

## Generative process

### New-car OTR series (`otr.py`)

Quarterly series per variant:

```
otr(t) = base_otr × (1 + annual_inflation)^(t − 2024) × brand_drift
```

`annual_inflation` is drawn once per variant from 3.2–7.1 %, so models drift
apart slowly rather than moving in lockstep — which is what gives the
residual-value anchor anything to do.

**Stated simplification:** the series continues past a generation's
`year_end`. A residual ratio needs a denominator at the auction date, and the
conventional denominator in residual-value work is the current new price of
the nearest equivalent. Those rows are labelled
`(reference, out of production)`.

### Auction records (`auction.py`)

```
value = otr_at_auction
      × 0.82                        # new→used drop + auction discount
      × exp(−k × age)               # k is the model's depreciation constant
      × odometer_effect             # vs a 15,000 km/year baseline
      × condition_effect            # from the damage score
      × location_effect             # branch price level
      × seller_effect               # leasing < fleet < dealer < individual
      × colour_effect               # common colours carry no penalty
      × market_index(t)             # slow trend + annual seasonal cycle
      − tax_penalty                 # flat IDR, mirrors the cold-start table
```

Bidding is then simulated:

```
demand  = value × LogNormal(0, 0.075)
reserve = value × Normal(0.94, 0.10)        # the seller's belief, with error
bidders ~ Poisson(λ(desirability))

bidders == 0        → NO_BID
demand ≥ reserve    → SOLD, clearing between reserve and demand
otherwise           → BELOW_RESERVE, highest_bid = demand
```

**Unsold units are generated on purpose and must stay in the training set.**
They are left-censored observations: the true value was below the reserve by
an unknown amount. Training only on sold units biases the model upward and
inflates floor prices — the exact failure this system exists to prevent
(§8.3).

Calibration targets, asserted by `tests/test_seed_calibration.py`:

| Quantity | Target band |
|---|---|
| Sold share | 0.60 – 0.75 |
| No-bid share | 0.06 – 0.16 |
| Median residual ratio (sold) | 0.30 – 0.70 |

### Deliberate imperfections

Clean synthetic data produces a pipeline that has never met a real record.
These rates are injected on purpose:

| Imperfection | Rate | What it exercises |
|---|---|---|
| Missing odometer | 9 % | Null handling; the feature must not be imputed to zero |
| Inconsistent `tipe` | 22 % | The catalog normaliser and fuzzy matcher (§6.1) |
| Missing transmission | 31 % | The gap the variant catalog exists to close |
| Missing grade | 7 % | Units predating graded intake |
| Duplicate records | 1.2 % | Deduplication — flagged, never deleted |
| Outlier prices | 0.6 % | Training-set outlier exclusion |
| Dirty/missing colour | 4 % | Categorical handling |

`tipe` corruption applies one of thirteen templates — trailing spaces, lowercase,
`A/T` suffixes, bare manufacturer codes, `ALL NEW` prefixes — because that is
how the same variant actually arrives from a source system.

### Imagery (`images.py`)

Drawn shapes and text, not photographs. Their purpose is to exercise the
capture quality gate, the perceptual-hash reuse detector, the OCR/vision stub
providers, and the review UI. **A real detector trained on these would learn
nothing transferable.**

Six degradation profiles are applied at realistic rates. Two of them
(`blurred`, `dark`) are expected to be *rejected* by the quality gate, so the
seeded set exercises both sides of every threshold.

| Profile | Share | Gate |
|---|---|---|
| clean | 44 % | accept |
| worn | 24 % | accept |
| glare | 13 % | accept |
| partially obscured | 9 % | accept |
| blurred | 6 % | **reject** |
| dark | 4 % | **reject** |

Exterior sets cover all nine mandatory angles with known damage labels.
Damage is only placed on panels actually visible from that angle — a provider
reporting a rear-bumper dent from a front photo would otherwise pass unnoticed.

### Seeded defect cases

Planted at fixed unit codes so M2 tests reference them by name rather than
scanning for them:

| Unit | Case | Expected verdict |
|---|---|---|
| `SYN-U-0000` | VIN mismatch | `MISMATCH` (BLOCKER) |
| `SYN-U-0001` | VIN differs by 1 char | `NEEDS_REVIEW` |
| `SYN-U-0002` | O/0 and I/1 only | `PASS`, `normalisation_applied = true` |
| `SYN-U-0003` | Engine number mismatch | `MISMATCH` (BLOCKER) |
| `SYN-U-0004` | Tampered plate | `TAMPERED_SUSPECTED` (BLOCKER) |
| `SYN-U-0005` | Odometer rollback (~1,100 km/yr at 8 years) | `MISMATCH` (BLOCKER) |
| `SYN-U-0006` | Photo reuse — STNK byte-identical to `SYN-U-0000` | phash collision (BLOCKER) |
| `SYN-U-0007` | Tax expired ≥ 12 months | `WARNING`, material cost item |
| `SYN-U-0008` | `tipe` matches no catalog entry | unresolved variant, pricing blocked |
| `SYN-U-0009` | Low OCR confidence on 4 fields | routed to verification queue |

`SYN-U-0002` is the one worth dwelling on: ISO 3779 excludes `I`, `O` and `Q`
precisely because they are confusable with `1` and `0`, and OCR makes the same
confusion. That case must resolve to `PASS` — but with `normalisation_applied`
recorded, so a match that only holds after normalisation stays distinguishable
from an exact one in the audit trail.

## Output

```
seed/output/images/<unit-code>/*.jpg   rendered captures
seed/output/image_manifest.json        every image, its hash, its ground truth
seed/output/seed_summary.json          calibration summary and demo credentials
seed/fixtures/ocr/index.json           stub OCR provider answers, keyed by sha256
seed/fixtures/vision/index.json        stub vision provider answers, keyed by sha256
```

Fixtures are keyed by image content hash rather than filename, so the stub
providers need no extra plumbing — they hash the bytes they were handed and
look up the answer. A re-encoded image stops matching, which is correct: it is
a different image.
