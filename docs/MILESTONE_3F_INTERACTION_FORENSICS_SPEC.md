# Milestone 3F — Nonlinear Interaction Forensics and External Validation

## Status

Frozen before Stage 3F empirical results are observed.

## Motivation

Stage 3E's predeclared primary candidate (`hgb_timing_inventory`) did **not** pass its advancement gate: although weighted MAE improved, Brier improved on only 3/7 held-out windows. A secondary ablation (`hgb_all`) was substantially stronger, improving weighted MAE on 7/7 windows and Brier on 6/7 windows relative to the Stage 3D transparent timing+inventory hurdle.

Because `hgb_all` was a secondary discovery, Stage 3F treats it as a hypothesis to interrogate rather than as a confirmed winner. The central question is whether the apparent gain comes from stable nonlinear interactions involving causal BTC state, or from chance/regime-specific structure in the original August 7–13 sample.

## Scientific claims permitted

Stage 3F may support statements about held-out explanatory association and temporal generalization. It must not describe the models as a deployable trading signal, profitable strategy, or causal mechanism.

## Frozen discovery panel

Use the same seven six-hour windows used in Stages 3C–3E:

- 2026-08-07 through 2026-08-13
- 12:00–18:00 UTC each day
- same account, BTC 5-minute market filter, FIFO pairing, causal feature materialization, and Coinbase 60-second reference data

No discovery-window selection may change after Stage 3F begins.

## Feature families

Use the existing Stage 3D/3E definitions without feature engineering based on Stage 3F outcomes:

- `T`: timing features
- `I`: contemporaneous inventory/execution-state features approved in Stage 3D
- `B`: usable causal BTC features from Stage 3C

Unavailable 15s/30s BTC and realized-volatility fields remain excluded.

## Discovery interaction-forensics tests

All model hyperparameters remain exactly those frozen for Stage 3E HGB unless a test explicitly concerns feature removal/permutation.

### 1. Individual BTC add-back ablations

Fit/evaluate `T + I + {b}` separately for every usable BTC feature `b`, using the same leave-one-calendar-window-out folds. Compare each to `T + I` and to `T + I + B`.

Purpose: identify whether the Stage 3E all-feature gain is broad or dominated by one BTC variable.

### 2. BTC group ablations

Evaluate at minimum:

- `T + I`
- `T + B`
- `I + B`
- `T + I + B`

The original Stage 3E all-feature result is a reference, not an advancement decision by itself.

### 3. Held-out-window permutation tests

For each held-out window and each usable BTC feature, permute that BTC feature **within the held-out window only**, leaving trained models and all non-BTC features unchanged. Use deterministic seeds.

Also perform a joint permutation of all BTC features using a shared row permutation so their internal cross-feature structure is preserved while their alignment to timing/inventory/outcomes is broken.

Report changes in weighted MAE and Brier relative to the unpermuted prediction. A useful BTC contribution should generally degrade when its held-out alignment is destroyed.

### 4. Permutation importance

Report held-out permutation importance for all usable T/I/B features for regression and classification separately. Aggregate by feature and feature family, but retain per-window values.

Do not use impurity-based tree importance as the primary importance statistic.

### 5. Interaction-family tests

Use controlled feature-family comparisons to estimate whether the BTC gain is more consistent with:

- BTC × timing structure (`T+B` versus corresponding components),
- BTC × inventory structure (`I+B` versus corresponding components), or
- three-family structure (`T+I+B` beyond both `T+I` and the strongest two-family BTC model).

These are explanatory interaction diagnostics, not causal interaction estimates.

## External temporal validation

The discovered `T+I+B` candidate must be evaluated on a **new historical period that was not used in Stages 3C–3E**.

### Frozen external period

Use seven six-hour windows:

- 2026-07-24 through 2026-07-30
- 12:00–18:00 UTC each day

This period is separated from the discovery sample and must be collected/materialized with the same accounting and causal-data rules.

### External models

Train candidate models using the complete original August 7–13 discovery panel only. Do not refit or tune using July outcomes. Score each July day independently and report both per-day and aggregate metrics.

At minimum compare:

- transparent Stage 3D timing+inventory model,
- Stage 3E HGB timing+inventory,
- Stage 3E HGB all (`T+I+B`).

For classification and regression, preprocessing must be fitted only on the August discovery panel.

## External confirmation gate

The Stage 3E `hgb_all` discovery is considered externally supported only if all of the following hold on the frozen July period:

1. aggregate weighted MAE is lower than HGB timing+inventory;
2. aggregate Brier is lower than HGB timing+inventory;
3. `hgb_all` wins on weighted MAE on at least 4 of 7 July days;
4. `hgb_all` wins on Brier on at least 4 of 7 July days;
5. aggregate weighted MAE is lower than the transparent timing+inventory baseline;
6. aggregate Brier is lower than the transparent timing+inventory baseline.

This gate is deliberately stricter than simply reproducing the Stage 3E pooled improvement.

## Interpretation rules

- If the external gate fails, treat the Stage 3E all-feature result as discovery-sample-specific unless later evidence says otherwise.
- If the gate passes but BTC permutation tests show little degradation, do not claim BTC is the source of the improvement; investigate model regularization/regime proxies first.
- If the gate passes and BTC permutation/add-back evidence is consistent across windows, Stage 3G may test richer interaction models, including a small neural network, under a newly frozen protocol.
- Neural-network work must not begin merely because an in-sample or discovery-panel importance statistic looks large.

## Required artifacts

Stage 3F must emit machine-readable and human-readable evidence including:

- discovery ablation fold metrics and summaries;
- individual BTC add-back results;
- per-feature and joint BTC permutation results;
- held-out permutation importance by window/model/target;
- external July panel coverage/provenance diagnostics;
- external per-day predictions/metrics for all required models;
- explicit external-gate booleans and overall decision;
- methodology/limitations report.

All artifacts must retain enough provenance to identify source windows, source resolution, model parameters, feature sets, and code commit.
