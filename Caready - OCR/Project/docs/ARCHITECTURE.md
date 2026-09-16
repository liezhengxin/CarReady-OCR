# Architecture

Vehicle inspection and auction base-price system for Caready. Under 100
units/day, so this is engineered for **correctness, auditability, and
unreliable field networks** — not for scale.

---

## End-to-end flow

```
Inspector (mobile PWA)
  → Intake capture: VIN plate, STNK front, odometer, engine number
  → ICR/OCR extraction + cross-checks (fraud layer)
  → Unit created in inventory dashboard
  → Exterior photo set: 9 mandatory angles + damage close-ups
  → AI visual damage detection → grade
  → Auction Market Price (AMP)   = P50, reference condition
  → Base price                   = P30, actual condition
  → Deduction                    = AMP − base price  (derived, not tabulated)
  → Human approval
  → Published base price
```

**Scope boundary.** Exterior condition only. Interior, engine, transmission,
chassis, and flood/accident history are out of scope for AI assessment — which
is exactly why the mandatory non-visual checklist exists (§8.4). Exterior-only
grading systematically overvalues mechanically damaged units, and no amount of
model quality fixes a missing feature.

---

## Repository layout

```
apps/web            Next.js PWA (inspector) + dashboard, one deployable
services/api        FastAPI — HTTP surface, auth, state machine, audit
services/worker     RQ workers — ICR, vision, pricing, purge jobs
packages/ml         Training + inference, provider interfaces, model cards
packages/scraper    New-car OTR price ingestion adapters
config/             Versioned business rules (YAML)
seed/               Synthetic data generators
infra/              Dockerfiles, compose, CI
docs/               This file, OPEN_ITEMS, MODEL_CARD, PDP
```

---

## Technology decisions and why

| Layer | Choice | Reasoning |
|---|---|---|
| Inspector app | Next.js PWA | Responsive mobile web is a requirement; PWA adds the offline capture queue the yard needs |
| Offline queue | IndexedDB (Dexie) + resumable upload | Yard/pool networks drop mid-upload |
| Backend | Python 3.11 + FastAPI | ML is Python. One language for API and modelling removes a serving bridge and its drift |
| DB | PostgreSQL 16 + Alembic | — |
| Object storage | S3-compatible | Photos never in the database |
| Jobs | Redis + RQ | ICR and vision are slow; the API must stay non-blocking |
| ML | LightGBM + scikit-learn | — |
| Tracking | MLflow | Model versions must be reproducible and auditable |

### Synchronous SQLAlchemy, deliberately

At under 100 units/day the concurrency argument for async is irrelevant, while
sharing one set of models and one session idiom between the API and the RQ
workers removes a whole class of duplicated data access. FastAPI runs sync path
operations in a threadpool, so the event loop is never blocked.

---

## Configuration: two kinds, kept apart

| | Settings | Business config |
|---|---|---|
| Where | environment variables | `config/*.yaml`, versioned in git |
| What | connection strings, secrets, toggles | grading rubrics, thresholds, weights, deduction tables |
| Changed by | deployment | product decision, reviewable by non-engineers |
| Example | `DATABASE_URL` | `grading.yaml` band thresholds |

**Business rules never live in `Settings`, and secrets never live in YAML.**

There are no grading constants in Python. The M6 acceptance criterion — editing
`config/grading.yaml` changes grades with zero code changes — is a structural
property, not a promise.

Every config file carries a `version`, recorded on every row it influenced, so
a grade or price computed six months ago remains interpretable after a
threshold change.

---

## Data model: the load-bearing decisions

### AI output is never overwritten

A grade override writes a **new** `grades` row with `source=FINAL` and a
mandatory reason; the AI row survives with `source=AI`. Same for damage
detections (superseded, not mutated) and plate-condition assessments. Without
this, "the model was wrong" and "someone changed it" become indistinguishable
after the fact.

### Append-only audit, enforced by the database

`audit_log`, `unit_status_transitions`, and `pii_access_log` carry a
`BEFORE UPDATE OR DELETE` trigger that raises. An audit trail the application
can rewrite is not an audit trail, so the guarantee does not rest on every
future code path remembering it.

The one escape hatch is `caready.allow_append_only_purge`, set transactionally
by the PDP retention job — the single legitimate reason to delete.

Actor email and role are **snapshotted** onto each row rather than joined at
read time, so records still read correctly after a rename, role change, or
deletion.

### Unsold auction units are data, not absence

`auction_records` holds `NO_BID` and `BELOW_RESERVE` rows alongside `SOLD`.
They are left-censored observations: true value was below reserve by an unknown
amount. Dropping them biases the model upward and inflates floor prices —
precisely the failure this system exists to prevent. See
[MODEL_CARD.md](MODEL_CARD.md) for the censoring treatment.

### Variant identity carries provenance

Every unit records `variant_resolution_method` (`auto` / `manual` /
`unresolved`) and `variant_match_score`. Pricing **does not run** on an
unresolved variant — stricter than degrading confidence, and deliberate: a
price computed on a guessed variant looks authoritative and is directionally
wrong.

### Money is `Numeric`, never float

A float rupiah figure accumulates rounding error across aggregations and cannot
be reconciled against an accounting system.

---

## Identity resolution: STNK is authoritative

**The STNK is the source of truth for brand, type, model, and year. The VIN
plate is a cross-check, not the primary decoder.**

There is no public VIN decoding database for the Indonesian market equivalent
to NHTSA vPIC, and many domestic CKD units do not follow ISO 3779 conventions
for the model-year character. A VIN-primary design produces a low decode
accuracy that cannot be repaired downstream.

VIN decoding is therefore an **optional enrichment layer**:

- WMI (chars 1–3) against `config/vin_wmi.yaml`, seeded and marked
  `verified: false` until checked against Caready's own data.
- VDS → variant mapping built **empirically** from units a human resolved,
  with a support count and a purity threshold. Never assumed from the standard.
- Disagreement raises a flag. It never overwrites an STNK value.

---

## The fraud layer

Seven cross-checks, each emitting a typed verdict and severity. **No check ever
auto-corrects.**

| Check | Blocking condition |
|---|---|
| VIN match | Mismatch beyond Levenshtein 2 → BLOCKER |
| Engine number match | Same → BLOCKER |
| Plate condition | `TAMPERED_SUSPECTED` → BLOCKER |
| Odometer sanity | < 1,000 km/yr on a 5+ year unit → BLOCKER |
| Photo reuse | Perceptual-hash collision across units → BLOCKER |
| Field confidence | Below threshold → verification queue |
| Tax status | Expired ≥ 12 months → WARNING, material cost item |

**Character normalisation is recorded, not just applied.** ISO 3779 excludes
`I`, `O`, and `Q` because they are confusable with `1` and `0`; OCR makes the
same confusion. Both sides are normalised before comparison — and
`normalisation_applied` is stored, so a match that only holds after
normalisation stays distinguishable from an exact one in the audit trail.

---

## Pricing: two layers

**Layer 1 — residual value anchor.** Realised price as a share of new-car OTR,
per `(variant, model_year)`, shrunk toward progressively coarser parents
(model+year → model → segment+age → age) using a James–Stein weight
`n / (n + k)`. This keeps rare models sane and is the fallback when ML support
is thin.

**Layer 2 — LightGBM quantile regression** on log price, with the Layer 1
anchor as its key feature. Three models: P30, P50, P70.

OLS and ridge are trained as **baselines for comparison and explainability
only**. If LightGBM does not clearly beat them on holdout, that is reported in
the model card — not hidden.

### Why the deduction is derived, not tabulated

```
AMP        = P50, unit in reference condition
Base price = P30, unit in actual condition
Deduction  = AMP − base price
```

Damage and grade are already model features. Predicting twice and showing the
difference keeps the number explainable to a human **without being arbitrary**.
A hardcoded deduction table bolted on top of a model prediction would double-count
condition and produce a figure nobody can defend.

The cold-start table in `config/deduction_coldstart.yaml` is used **only** at
data-sufficiency tier `COLD_START`, is flagged on the price result, degrades
confidence, and is surfaced in the UI.

A database CHECK constraint asserts `|deduction − (amp − base_price)| < 1`, so
no future code path can quietly write a deduction from a table instead.

---

## Approval workflow

```
DRAFT → ICR_DONE → GRADED → PRICED → PENDING_APPROVAL → APPROVED | REJECTED
```

**No AI-generated price is ever published without human approval.** The
transition into `APPROVED` is always actor-driven; `automated` is recorded on
every transition so this is verifiable rather than asserted.

Hard blocks on auto-progression: VIN mismatch, tampered plate, unresolved
variant, odometer anomaly, any flagged non-visual checklist item.

Blockers evaluated at each transition are recorded **even when empty**, so the
absence of a block is itself evidenced.

---

## Roles

| Role | Capability |
|---|---|
| `inspector` | Create units, capture, submit. **Cannot see prices.** |
| `appraiser` | Full view, override grade and damage with mandatory reason, see AMP and base price. Cannot approve. |
| `approver` | Everything an appraiser can, plus approve/reject. |
| `admin` | Users, config, catalog curation, model deployment. |

**Inspectors not seeing prices is a control, not a UI preference.** An
inspector who can see the price a unit is heading toward has an incentive to
shade damage reporting toward it. Enforced server-side: price fields are
omitted from the serialised response, not hidden by the client.

Checks are **capability-based**, not role-based — `require(Capability.X)`
rather than `require_role("appraiser")` — so a permissions change is one edit
to `ROLE_CAPABILITIES` in `app/enums.py`, not a hunt through route decorators.

---

## Data protection

Built in from M2, not retrofitted. See [PDP.md](PDP.md).

- PII columns encrypted at rest with Fernet; keys from the environment,
  rotatable via `MultiFernet`.
- Masked by default everywhere. Unmasking requires `pii:unmask` and writes an
  access record — including for **denied** attempts.
- The audit log stores *that* a PII field changed, never the value. Copying
  plaintext PII into an append-only table would create a second, unerasable
  copy.
- Photos served only through short-lived signed URLs; buckets are private.
- Structured logs pass through a redaction filter keyed on field-name suffixes,
  so a careless log call cannot leak PII.

`nomor_registrasi` is deliberately **not** encrypted: it is the primary
operational lookup key and an encrypted column cannot be indexed. It is
protected by masking and access logging instead. That trade-off is recorded in
`config/pdp.yaml`.

---

## Observability

Structured JSON logs (structlog). A request id flows from the client header
through every log line, every audit row, and every job run — so "why was this
unit blocked?" is answerable from either end.

`/healthz` is liveness and deliberately does **not** touch the database: a
liveness probe that fails on a transient database blip gets the container
killed, which fixes nothing. `/readyz` checks dependencies and removes the
instance from the load balancer instead.

---

## Known architectural debts

1. **Baseline migration uses `create_all`** — see [OPEN_ITEMS.md #8](OPEN_ITEMS.md).
2. **No rate limiting implemented yet** — `api_rate_limit_per_minute` is
   configured but unenforced. M8.
3. **MLflow on a file/SQLite backend** — fine for a single-node dev stack,
   needs a real backing store before multi-user model tracking.
4. **`packages/scraper` is interface-only at M0** — adapters land at M4.
