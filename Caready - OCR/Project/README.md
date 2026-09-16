# Caready — Vehicle Inspection & Auction Base Price System

Vehicle inspection, exterior condition grading, and defensible auction base
price (*harga dasar lelang*) for Caready.

> ## ⚠️ All data in this repository is synthetic
>
> The seed generators produce fabricated vehicles, auctions, prices, documents,
> and owners. **No model output derived from this data is evidence of pricing
> accuracy.** It demonstrates that the pipeline runs end to end — nothing more.
>
> The running system enforces this: a non-dismissible banner while
> `SYNTHETIC_DATA_MODE` is on, `is_synthetic = true` on every seeded row, and
> `trained_on_synthetic = true` on any model trained from it.

---

## Status

**M0 complete (code).** See [`docs/OPEN_ITEMS.md`](docs/OPEN_ITEMS.md) for what
is unresolved, and the milestone report for what remains unverified.

| M | Deliverable | Status |
|---|---|---|
| M0 | Monorepo, Compose, CI, migrations, synthetic data | code complete, unverified |
| M1 | Inspector PWA intake capture | not started |
| M2 | ICR pipeline + cross-checks | not started |
| M3 | Inventory dashboard + review queue | not started |
| M4 | Variant catalog + price references | not started |
| M5 | Pricing engine | not started |
| M6 | Exterior grading | not started |
| M7 | Base price + approval workflow | not started |
| M8 | Hardening | not started |

---

## Quick start

**Prerequisites:** Docker Desktop (WSL2 backend on Windows), and — for running
anything outside containers — Python 3.11 and Node 22.

```bash
cp .env.example .env
docker compose up --build
```

That brings up PostgreSQL, Redis, MinIO, MLflow, the API, a worker, and the web
app, applies migrations, and seeds synthetic data.

| Service | URL |
|---|---|
| Web | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |
| MLflow | http://localhost:5500 |

Demo accounts, password `caready-dev-2026`:

| Email | Role | Sees prices |
|---|---|---|
| `inspektur@caready.local` | inspector | **no** — by design |
| `penilai@caready.local` | appraiser | yes |
| `penyetuju@caready.local` | approver | yes, and can approve |
| `admin@caready.local` | admin | config and catalog |

---

## Layout

```
apps/web            Next.js PWA (inspector) + dashboard
services/api        FastAPI — HTTP, auth, state machine, audit
services/worker     RQ workers — ICR, vision, pricing, purge
packages/ml         Training + inference, provider interfaces
packages/scraper    New-car OTR price ingestion adapters
config/             Versioned business rules (YAML)
seed/               Synthetic data generators
infra/              Dockerfiles, CI
docs/               Architecture, open items, model card, PDP
```

---

## Business rules live in `config/`, not in code

There are no grading constants, thresholds, or deduction values in Python.
Every one of them is in a versioned YAML file, and the version is recorded on
every row it influenced — so a grade computed six months ago stays
interpretable after a threshold change.

| File | Governs |
|---|---|
| `grading.yaml` | Grade bands, panel weights, damage points, downgrade rules |
| `pricing.yaml` | Quantiles, censoring, features, confidence, guard rails |
| `crosschecks.yaml` | The fraud layer — VIN, engine, tax, odometer, photo reuse |
| `capture.yaml` | Quality gates, required angles, offline queue |
| `catalog.yaml` | Variant matching thresholds and the learning loop |
| `deduction_coldstart.yaml` | Cold-start fallback only, not the pricing mechanism |
| `pdp.yaml` | PII classification, masking, retention |
| `providers.yaml` | OCR/vision/price-source implementation selection |

`config/grading.yaml` and `config/deduction_coldstart.yaml` are **placeholders**
and say so in machine-readable form. The API propagates that to a UI warning
and a pricing-confidence degradation.

---

## Common commands

```bash
# Tests
cd services/api && pytest                    # API
pytest seed/tests                            # generator determinism & calibration
cd apps/web && npm test

# Migrations
cd services/api
alembic upgrade head
alembic revision --autogenerate -m "describe the change"
alembic check                                # schema vs ORM metadata

# Seed
python seed/run_seed.py                      # full, with imagery
python seed/run_seed.py --no-images --reset  # fast reseed

# Lint
ruff check services packages seed
ruff format services packages seed
```

---

## Design decisions worth knowing before reading the code

**The STNK is authoritative for brand, type, model, and year.** The VIN plate
is a cross-check, not the primary decoder. There is no public Indonesian
equivalent of NHTSA vPIC, and many domestic CKD units ignore ISO 3779
conventions for the model-year character. VIN decoding is an optional
enrichment layer that can raise a flag and can never overwrite an STNK value.

**Unsold auction units are training data, not missing data.** They are
left-censored observations. Training only on sold units biases the model upward
and inflates floor prices — the exact failure this system exists to prevent.

**The deduction is derived, not tabulated.** Damage and grade are already model
features. AMP is the P50 at reference condition, base price the P30 at actual
condition, and the deduction is the difference. A table applied on top of a
prediction would double-count condition. A database CHECK constraint enforces
the arithmetic.

**Pricing does not run on an unresolved variant.** Stricter than degrading
confidence, and deliberate: a price computed on a guessed variant looks
authoritative and is directionally wrong. The STNK does not record transmission
at all, and its `tipe` field is often a manufacturer code.

**Inspectors cannot see prices.** Enforced server-side — price fields are
omitted from the response, not hidden by the client. An inspector who can see
the target price has an incentive to shade damage reporting toward it.

**AI output is never overwritten.** An override writes a new row with a
mandatory reason; the AI value survives. Otherwise "the model was wrong" and
"someone changed it" become indistinguishable.

**The audit trail is append-only at the database level.** A `BEFORE UPDATE OR
DELETE` trigger raises. An audit trail the application can rewrite is not an
audit trail.

**Exterior grading cannot see everything, so a checklist gates approval.**
Flood damage, chassis repair, engine and transmission condition, and odometer
tampering are invisible to exterior AI. Without the mandatory non-visual
checklist, mechanically damaged units are systematically overpriced — and the
error is invisible in the metrics, because the model never had the feature.

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and the reasoning behind it |
| [OPEN_ITEMS.md](docs/OPEN_ITEMS.md) | Unresolved questions — **read this first** |
| [MODEL_CARD.md](docs/MODEL_CARD.md) | Pricing model design, censoring, limitations |
| [PDP.md](docs/PDP.md) | UU PDP No. 27/2022 compliance design |
| [seed/README.md](seed/README.md) | The synthetic generative process, stated in full |
