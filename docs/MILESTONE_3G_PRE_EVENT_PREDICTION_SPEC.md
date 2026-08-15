# Milestone 3G — Strict Pre-Event Prediction

## Status

Frozen before Stage 3G empirical results are observed.

## Motivation

Stages 3C–3F established that causal BTC state and contemporaneous inventory/execution state explain complementary-pair outcomes across held-out days and an untouched July validation period. Stage 3F externally confirmed the nonlinear all-feature candidate, with the strongest forensic evidence centered on BTC 60-second return interacting with inventory/execution state.

However, the strongest inventory features used so far are contemporaneous with the pair-forming execution. They are appropriate for forensic explanation but insufficient for a prospective trading claim.

Stage 3G therefore changes the prediction boundary. Every predictor must be reconstructable strictly before the target execution/event. The objective is to determine whether information available beforehand contains stable held-out information about the next complementary execution outcome.

## Claims permitted

Stage 3G may support statements about historical pre-event predictive association and temporal generalization. Passing Stage 3G does **not** establish live profitability, executable edge, or expected trading profit after fees, latency, spread, queue position, slippage, or market impact.

A successful Stage 3G earns progression to prospective shadow-mode validation.

## Prediction unit and timestamp

The prediction unit is an eligible FIFO complementary pair event under the existing accounting rules.

For each target pair event, define `prediction_time` as the timestamp immediately before the execution that completes that FIFO pair event. All account-state features must be computed from fills with timestamps/order positions strictly preceding that completing execution. The completing execution itself and any later execution are forbidden inputs.

When multiple fills share a timestamp, deterministic source ordering must be preserved. Only fills ordered before the target fill may contribute to the snapshot. Same-timestamp fills ordered after or equal to the target are unavailable.

## Target variables

Preserve the established targets:

1. continuous realized FIFO `pair_cost` for the completed complementary pair;
2. binary `favorable = pair_cost < 1.0`.

Targets are labels only and must never influence pre-event feature construction.

## Strict leakage rules

For target event `e`, no feature may use:

- target execution price, quantity, side, token, or resulting inventory mutation except information already known before the target execution;
- post-target fills;
- cumulative VWAP or complete-set-cost values updated by the target execution;
- rolling counts/quantities that include the target execution;
- BTC candles whose causal availability timestamp is after `prediction_time`;
- market outcome/resolution information unavailable at `prediction_time`.

The materializer must emit provenance sufficient to audit the maximum source timestamp/order position for every pre-event snapshot.

Automated guardrails must fail the workflow if a snapshot violates these rules.

## Pre-event feature families

### Timing (`T_pre`)

Features known before the target execution, including the existing market elapsed/remaining-time representation and lag/state variables that can be calculated without observing the completing fill.

### Inventory/execution state (`I_pre`)

Reconstruct account state immediately before the target execution. Candidate fields are limited to state derivable from prior fills, including:

- UP inventory;
- DOWN inventory;
- paired inventory;
- residual inventory;
- inventory imbalance;
- time since prior UP fill;
- time since prior DOWN fill;
- trailing fill counts and quantities over established 15s/30s/60s windows, excluding the target execution;
- trailing side switches;
- cumulative paired quantity before the target;
- prior same-second activity, excluding the target and later same-timestamp fills.

Contemporaneous post-target VWAP/complete-set-cost fields remain excluded.

### BTC (`B_pre`)

Use only the Stage 3C causal BTC fields whose reference data is available by `prediction_time`. Preserve the existing 60-second Coinbase provenance/availability rule.

The primary BTC hypothesis remains `btc_return_60s`; other previously usable causal BTC fields may be retained in the all-feature ablation. Unsupported 15s/30s returns and realized-volatility fields remain excluded.

## Frozen model families

No hyperparameter search is permitted in Stage 3G.

Evaluate:

1. transparent pre-event timing+inventory baseline using the established Stage 3D linear/logistic machinery;
2. HGB `T_pre + I_pre` using the exact Stage 3E HGB parameters;
3. HGB `T_pre + I_pre + btc_return_60s`;
4. HGB `T_pre + I_pre + B_pre`.

This isolates whether the Stage 3F BTC finding survives the stricter prediction boundary.

## Discovery/training period

Use the established August discovery period:

- 2026-08-07 through 2026-08-13
- 12:00–18:00 UTC each day

For discovery diagnostics, retain leave-one-calendar-window-out evaluation. Preprocessing/model fitting must use training windows only.

## Frozen untouched validation period

Use a new period not used for model evaluation in Stages 3C–3F:

- 2026-07-10 through 2026-07-16
- 12:00–18:00 UTC each day

Train final Stage 3G candidates on the complete August 7–13 pre-event panel only. Do not tune, refit, calibrate, select features, or change thresholds using July 10–16 outcomes.

Each July day must be reported separately as well as in aggregate.

## Advancement gate to prospective shadow mode

The primary candidate is HGB `T_pre + I_pre + B_pre`.

Stage 3G passes only if all of the following hold on the frozen July 10–16 external period:

1. aggregate weighted MAE is lower than HGB `T_pre + I_pre`;
2. aggregate Brier is lower than HGB `T_pre + I_pre`;
3. BTC-all wins weighted MAE on at least 4 of 7 external days;
4. BTC-all wins Brier on at least 4 of 7 external days;
5. aggregate weighted MAE is lower than the transparent pre-event timing+inventory baseline;
6. aggregate Brier is lower than the transparent pre-event timing+inventory baseline;
7. strict leakage/provenance guardrails pass for 100% of evaluated rows;
8. every external day contains sufficient eligible events to report independently.

Additionally report the single-feature `btc_return_60s` candidate. It is diagnostically important but is not allowed to replace the frozen primary gate after results are observed.

## Secondary diagnostics

Report without using them to rewrite the advancement gate:

- per-day and aggregate target prevalence;
- pre-event feature coverage;
- pair-cost distribution by day;
- performance by market elapsed-time bucket;
- performance by pre-event inventory-imbalance bucket;
- performance by BTC 60s-return bucket;
- calibration/reliability diagnostics for the binary target;
- prediction dispersion and degenerate-prediction checks;
- comparison with contemporaneous Stage 3F performance to quantify how much explanatory power disappears when the target execution is removed from the features.

## Required causal/provenance tests

Tests must demonstrate at minimum:

- target execution cannot mutate its own snapshot;
- later fills cannot mutate an earlier snapshot;
- same-timestamp source ordering is respected;
- rolling windows exclude the target execution;
- inventory state equals state after the immediately preceding eligible fill;
- BTC source availability is not later than prediction time;
- feature materialization is deterministic under identical ordered input;
- external validation never enters fitting/preprocessing.

## Required artifacts

Stage 3G must emit machine-readable and human-readable evidence including:

- frozen discovery and external manifests;
- pre-event feature panels or reproducible panel provenance;
- leakage audit/guardrail report;
- feature coverage report;
- discovery held-out fold metrics;
- external per-day metrics and aggregate summaries;
- external gate booleans and overall PASS/FAIL;
- model/feature definitions and fixed parameters;
- methodology and limitations report;
- source/code commit provenance.

## Interpretation after Stage 3G

If the external gate passes, the next workstream should be a live **shadow-mode application** that computes the same pre-event state prospectively and records signals/outcomes without submitting orders. A small neural-network challenger may be evaluated only under a separately frozen protocol and should not delay prospective validation of a Stage 3G model that passes.

If the gate fails, do not weaken it post hoc. Use the diagnostics to determine whether the Stage 3F result depended materially on contemporaneous execution information, and redesign only in a newly declared milestone.