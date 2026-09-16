# Open items

Unresolved questions carried forward rather than silently decided. Each has a
documented default behind config so the system runs, and each default is
visible in the UI so nobody mistakes a placeholder for a decision.

**This file is updated at every milestone report.** An item is only closed when
Caready has confirmed the answer — not when a developer picks something
reasonable.

Status key: 🔴 blocking accuracy · 🟠 blocking go-live · 🟡 needs a decision · ⚪ engineering

Last updated: **M0** (2026-09-15)

---

## 1. 🔴 Caready's actual grading scale and rubric

**Question.** What grades does Caready use, what are the band thresholds, and
how are damage types and panels weighted?

**Current behaviour.** A documented placeholder in [`config/grading.yaml`](../config/grading.yaml):
an additive damage-point model, bands A–E, plus six automatic downgrade rules.
`rubric_status: PLACEHOLDER` propagates to a warning banner on every unit, a
`rubric_placeholder = true` flag on every stored grade, and a one-level
pricing-confidence degradation.

**Why it cannot be deferred indefinitely.** Grade is a pricing feature. A grade
scale that does not match how Caready's appraisers actually think produces a
feature that correlates with nothing they can act on, and the model learns the
placeholder's biases rather than the market's.

**What we need.** The grade labels, the boundary between each, and — most
valuably — 30–50 units an experienced appraiser has already graded, with
photos. That lets the placeholder be calibrated rather than replaced blind.

**Owner:** Caready operations · **Blocks:** M6 sign-off

---

## 2. 🔴 Labelled historical photo/grade data for Stage 2 vision

**Question.** Does Caready hold historical exterior photo sets with
per-damage labels, or with grades that could be back-attributed?

**Current behaviour.** Stage 1 only: a vision-language model behind
`VisionProvider` with a strict JSON schema. Every appraiser correction is
written to `damage_corrections`, which is the deliberate flywheel — after
roughly 3–6 months that table becomes the Stage 2 training set.

**Why it matters now.** If labelled data already exists, Stage 2 starts months
earlier and the Stage 1 VLM cost is avoided sooner. If it does not, the label
store and its export tooling are on the critical path and must not be deferred.
The answer changes sequencing, not architecture — which is why the swap point
is built now either way.

**Owner:** Caready · **Blocks:** Stage 2 planning, not M6 delivery

---

## 3. 🟠 Legal position on scraping new-car prices

**Question.** Is scraping third-party sites for new-car OTR prices acceptable
to Caready, or should a licensed data feed be procured?

**Current behaviour.** CSV import is the guaranteed fallback and the CI
default. The web adapter exists behind the same interface, respects
`robots.txt`, rate-limits per domain, and identifies itself — but it is
**off by default**.

**The honest position.** Scraping third-party sites may violate their terms of
service and is operationally fragile: a site redesign silently degrades price
data, which corrupts the residual-value anchor that everything else depends on.
The mitigation implemented is that a selector yielding zero rows raises an
alert and fails, rather than returning stale data quietly.

**This is a commercial decision for Caready, not a technical one.** The adapter
interface exists so a licensed feed can replace it without touching the pricing
model.

**Owner:** Caready commercial/legal · **Blocks:** M4 production use

---

## 4. 🟠 Who owns and curates the variant catalog

**Question.** Which role at Caready owns catalog correctness day to day?

**Current behaviour.** Admin-role curation UI (M4) with merge, alias, and
correction actions; every edit is recorded in `catalog_curations`. Manual
resolutions feed the matcher automatically.

**Why an owner is needed, not just a tool.** The catalog is the single biggest
accuracy risk in the system. The STNK does not record transmission, and its
`tipe` field is often a manufacturer code rather than a readable trim. An
unresolved variant produces *systematic, directional* pricing error. The
matcher improves only as fast as someone resolves the queue — with no owner,
the unresolved queue grows and pricing quality degrades silently.

**Estimated load.** At under 100 units/day, expect 10–25 manual resolutions per
day initially, falling sharply as aliases accumulate.

**Owner:** Caready operations · **Blocks:** M4 operational readiness

---

## 5. 🟡 Reserve-price policy — is P30 the right risk posture?

**Question.** Base price is currently the P30 prediction. Is that the right
floor, and who owns changing it?

**Current behaviour.** `config/pricing.yaml` → `quantiles.base_price_quantile:
0.3`. Configurable without a code change.

**The reasoning.** Setting an auction floor is a risk decision, not a point
forecast. P50 would be right half the time and too high half the time; too high
means no sale, a relisting cost, and a stale unit. P30 trades a little realised
price for a materially higher sell-through.

**What we need.** Caready's tolerance, expressed as either a target
sell-through rate or an acceptable share of units clearing below expectation.
Either can be converted to a quantile. Also: who is authorised to change it, and
does it vary by seller type — a leasing portfolio and an individual consignment
plausibly want different postures.

**Owner:** Caready commercial · **Blocks:** M7 sign-off

---

## 6. 🟠 Is the non-visual checklist accepted as mandatory, and what is on it?

**Question.** Will Caready accept a mandatory inspector checklist gating base
price approval, and what exactly are its items?

**Current behaviour.** Seven items in `app.enums.NonVisualCheckItem`: flood
indication, chassis repair, engine condition, transmission condition, odometer
tampering, airbag deployed, document completeness. Any flagged item blocks
auto-approval and requires appraiser action.

**Why this is not optional engineering.** Exterior-only AI grading cannot see
flood damage, chassis repair, engine or transmission condition, or odometer
tampering. Without this gate, mechanically damaged units are *systematically*
overpriced — and the error is invisible in the metrics, because the model
never had the feature that would have caught it.

**What we need.** Confirmation the gate is acceptable operationally (it adds
inspection time), and the item list from someone who inspects these units.

**Owner:** Caready operations · **Blocks:** M7 sign-off

---

## 7. 🟠 STNK PII retention period and legal basis

**Question.** How long may `nama_pemilik`, `alamat`, and any NIK be retained
after a unit reaches a terminal status, and on what legal basis under
UU PDP No. 27/2022?

**Current behaviour.** Placeholder 1,095 days (3 years) in
[`config/pdp.yaml`](../config/pdp.yaml), with `retention.dry_run: true` — the
purge job reports what it *would* delete and deletes nothing. PII columns are
encrypted at rest, masked by default, and every unmasking writes an access
record.

**What we need.** The retention period, the legal basis for each processing
purpose, and confirmation of the deletion posture: currently
`pii_erasure_retain_deidentified`, which erases personal data but retains the
de-identified pricing record for model integrity. That reasoning needs legal
confirmation — it rests on the retained data no longer being personal data.

**Owner:** Caready legal · **Blocks:** production go-live

---

## 8. ⚪ Freeze the baseline migration to explicit DDL

**Raised at M0 by the build, not by the brief.**

`alembic/versions/0001_baseline.py` creates tables via
`Base.metadata.create_all()` rather than ~34 hand-written `op.create_table()`
calls, because it was authored before a toolchain was available to run
`alembic revision --autogenerate`. On a fresh database this is correct by
construction; a hand-transcribed baseline of that size could not be verified
without running it.

**The limitation.** `create_all` reads metadata as it exists when the migration
*runs*, not when it was *written*. Once a delta migration (0002+) exists, a
fresh `alembic upgrade head` would create the newest schema at 0001 and then
fail applying 0002.

**Remediation — do this on the first environment with a working toolchain, and
before authoring any delta migration:**

```bash
alembic upgrade head                            # against an empty database
alembic revision --autogenerate -m "baseline"   # capture explicit DDL
# replace the body of 0001_baseline.py with the generated op.create_table
# calls, keeping the raw DDL sections (triggers, trigram and partial indexes,
# cross-column CHECK constraints)
```

CI runs `alembic upgrade head` then `alembic check`, so ORM/schema divergence
fails the build in the meantime.

**Owner:** engineering · **Blocks:** the second migration

---

## 9. ⚪ Development environment provisioning

**Raised at M0.** The target workstation has no Python, Node.js, Docker, or
Git installed, so no part of this build has been executed — see the M0 report.
Every acceptance criterion is currently *unverified*, not *failing*.

**What we need.** Either a provisioned workstation (Docker Desktop with WSL2,
Python 3.11, Node 22, Git), or a CI-first workflow where GitHub Actions is the
first environment to run the stack.

**Owner:** Caready / engineering · **Blocks:** M0 acceptance sign-off

---

## Closed items

*None yet.*
