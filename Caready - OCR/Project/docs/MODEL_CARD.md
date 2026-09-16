# Model card — Caready auction base price

> **Status at M0: no model has been trained.**
>
> This card is the structure the M5 training run fills in, plus the design
> decisions already fixed in `config/pricing.yaml`. Metrics tables are empty on
> purpose — a model card with speculative numbers is worse than one with none.

---

## Intended use

Produce a defensible **auction base price** (harga dasar lelang) for a vehicle
entering a Caready auction, together with a price band, an explanation, and a
confidence level.

**Intended users.** Appraisers and approvers. Not inspectors — they cannot see
prices, by design (see [ARCHITECTURE.md](ARCHITECTURE.md#roles)).

**Out of scope.** Retail valuation, insurance write-off assessment, financing
collateral valuation. The training population is auction outcomes, which clear
below retail and under different conditions.

### Critical limitation: exterior only

The model sees exterior condition. It cannot see flood damage, chassis repair,
engine or transmission condition, or odometer tampering.

A unit that is cosmetically clean and mechanically ruined will be priced as
cosmetically clean. This is not a defect the model can be trained out of — the
feature is absent. It is the reason the **mandatory non-visual checklist**
(§8.4) gates approval, and the reason a flagged item blocks auto-progression.

---

## Model design

### Two layers

**Layer 1 — residual value anchor.** For each `(variant, model_year)`, the mean
ratio of realised auction price to new-car OTR price, shrunk toward
progressively coarser parents:

```
variant+year → model+year → model → segment+age → age
weight = n / (n + k),  k = 12
```

Cells with fewer than 3 observations contribute nothing. Ratios are winsorised
at the 2nd/98th percentile before aggregating, so one mis-keyed price cannot
move an anchor that a hundred units depend on.

**Layer 2 — LightGBM quantile regression** on `log(price)`, with the Layer 1
anchor as its key feature. Three models at α = 0.3, 0.5, 0.7.

### Why quantiles rather than a point estimate

Setting an auction floor is a risk decision. A point forecast answers "what
will this fetch?"; a floor needs "what will this fetch at least, with
acceptable confidence?" The base price is the **P30** — configurable, and its
correctness is [OPEN_ITEMS #5](OPEN_ITEMS.md).

Quantiles are trained independently, so crossing is possible. Monotonicity is
enforced at inference; a crossing is sorted **and flagged**, never silently
corrected.

### AMP and the deduction

```
AMP        = P50 prediction, unit in REFERENCE condition
Base price = P30 prediction, unit in ACTUAL condition
Deduction  = AMP − base price
```

The deduction is **derived by predicting twice**, not looked up in a table.
Damage and grade are already features; a table applied on top would
double-count condition and produce a number nobody can defend.

Reference condition is defined in `config/pricing.yaml` as a damage score
(12.0), not a grade label, so it survives a change to the grading scale.
"Typical condition for age and mileage" — not showroom new, which would inflate
the displayed deduction into a meaningless figure.

---

## Censoring: unsold units

**Unsold units are in the training set.** They are left-censored: true market
value was below the reserve, by an unknown amount. Training only on sold units
biases the model upward and inflates floor prices.

Implemented scheme (`config/pricing.yaml` → `censoring`), method
`weighted_bound`:

1. A censored row enters training with sample weight **0.45** (sold = 1.0), and
   its target imputed at `reserve × 0.93` — a deliberately conservative stand-in
   for "below reserve".
2. `NO_BID` rows carry a lower weight (**0.30**) than `BELOW_RESERVE` rows: a
   lot that attracted bids but missed reserve locates the true value far more
   precisely than one nobody bid on.
3. An auxiliary classifier `P(sells | price, features)` is trained on all rows
   and its output is returned alongside the price band.

**Why not Tobit or IPCW.** A Tobit likelihood is the textbook answer and is
cleaner statistically, but it does not compose with LightGBM's quantile
objective — we would lose the quantile band, which is the thing the business
decision actually needs. IPCW requires a censoring model that is itself
credible, and at cold start there is not enough data to fit one. The weighted
bound is cruder and its bias direction is known and conservative (it
under-states value for censored units, which errs toward a lower floor).

**This trade-off should be revisited once ~12 months of real graded history
exists.** If a change is made, it must be justified here, in writing.

---

## Features

| Group | Features |
|---|---|
| Age & use | `age_years`, `odometer_km`, `odometer_km_per_year` |
| Identity | `variant_id`, `transmission`, `body_type`, `engine_cc` |
| **Anchor** | `residual_anchor_ratio` ← Layer 1 output, the key feature |
| Reference price | `otr_price_at_auction` |
| Condition | `grade_label`, `damage_score`, `damage_count`, per-panel-group count and weighted severity, `celah_panel_present`, `rust_present`, `repaint_present` |
| Documents | `tax_status`, `months_to_tax_expiry` |
| Cosmetic | `colour`, `is_common_colour` |
| Market | `auction_location`, `auction_month_index`, `market_index`, `seller_type` |
| Demand history | `historical_bidder_count`, `historical_sell_through_rate` |
| Data quality | `variant_unresolved`, `non_visual_flagged` |

`celah_panel_present` is separated from the general damage score on purpose:
panel gap and misalignment is the strongest exterior-visible proxy for prior
collision repair, and a buyer discounts a repaired-collision car beyond its
cosmetic grade.

---

## Training protocol

**Temporal split, never random.** A random split leaks future market conditions
into training and flatters holdout metrics. Holdout is the final 4 months,
validation the 3 before that.

Minimum 2,000 training rows. MLflow experiment `caready-pricing`; every run
records the config snapshot, the anchor version, the feature list, and the
baseline comparison.

### Metrics reported

| Metric | Purpose |
|---|---|
| MAE, MAPE, RMSE | Central accuracy |
| Pinball loss (per quantile) | Whether each quantile is doing its job |
| P30–P70 coverage | Band calibration; target ≥ 0.40 |
| Beats-baseline flag | Whether LightGBM earns its complexity |

**The baseline comparison is reported whether or not it is flattering.**
LightGBM must beat the best of OLS/ridge on holdout MAE by ≥ 5% to be marked
`beats_baseline: true`. If it does not, that is a finding to report — the right
response may be that a regularised linear model is the correct production
choice for this data volume.

---

## Guard rails

A model that returns an absurd number must fail loudly rather than publish.

| Rail | Bound |
|---|---|
| Absolute price | 5,000,000 – 5,000,000,000 IDR |
| Share of new OTR | 3% – 100% |
| Quantile monotonicity | P30 ≤ P50 ≤ P70, enforced |

Violations block auto-progression and force appraiser review.

---

## Confidence

Starts HIGH, knocked down per triggered condition, floored at LOW. Every
trigger is listed on the price result so an approver sees exactly why.

| Condition | Levels |
|---|---|
| Variant unresolved | −2 *(pricing does not run at all)* |
| Data tier COLD_START | −2 |
| Any BLOCKER cross-check | −2 |
| Data tier THIN | −1 |
| Grading rubric is placeholder | −1 |
| Cold-start deduction table used | −1 |
| Grade provisional (incomplete photo set) | −1 |
| Odometer missing | −1 |
| Band width > 45% of P50 | −1 |

---

## Performance

### Holdout metrics

*Empty at M0 — no model trained.*

| Model | MAE | MAPE | RMSE | Pinball | Coverage |
|---|---|---|---|---|---|
| LightGBM P50 | — | — | — | — | — |
| OLS baseline | — | — | — | — | — |
| Ridge baseline | — | — | — | — | — |
| Residual anchor only | — | — | — | — | — |

### Performance by slice

To be reported at M5 across: data-sufficiency tier, variant resolution method,
seller type, grade band, age bucket, and branch. **Aggregate metrics hide the
failures that matter** — a model that is excellent on Avanzas and useless on
commercial vehicles has a good headline MAE.

---

## Training data

### At M0: synthetic only

**Any model trained now is trained on fabricated data and is recorded with
`trained_on_synthetic = true`.**

The synthetic generator uses an explicit parametric depreciation model (see
[seed/README.md](../seed/README.md)). A model trained on it will recover that
generator's own parameters. **That is not evidence of pricing accuracy** — it
is evidence the pipeline runs. Reporting a synthetic-data MAE as a performance
figure would be actively misleading, and the `trained_on_synthetic` flag exists
so it cannot happen by accident.

### Known biases to check on real data

- **Lease-return dominance.** If most volume is leasing repossessions, the
  model learns that population. Individual consignments may be systematically
  mispriced.
- **Geographic concentration.** Jabodetabek branches dominate volume; regional
  branch effects will be estimated from thin data.
- **Grade availability.** Units predating graded intake have no grade. Whether
  they are excluded or imputed materially changes the condition coefficient.
- **Variant resolution.** Auto-matched variants may carry systematic errors
  that manual resolutions do not. `variant_resolution_method` is a feature
  partly so this is measurable.

---

## Monitoring

Once live, track continuously:

- Realised price vs predicted, by tier and slice
- Actual P30–P70 coverage vs target
- Sell-through rate vs `P(sells)` prediction
- Appraiser override rate and direction — **a consistently directional override
  is the model being wrong, not the appraiser**
- Feature drift, especially `residual_anchor_ratio` and `otr_price_at_auction`
- Share of units at each data-sufficiency tier

Retrain trigger: monthly, or on a sustained MAE degradation beyond a threshold
to be set once a baseline exists.

---

## Changelog

| Date | Version | Change |
|---|---|---|
| 2026-09-15 | — | Card created at M0. No model trained. |
