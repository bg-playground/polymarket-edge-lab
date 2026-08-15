# Polymarket Edge Lab — Project State After Stage 3G

## Purpose

This document is the durable handoff from the historical/forensic research program through Stage 3G into Milestone 4A, the first prospective Live Shadow Engine.

It is intended to let a fresh engineering/research session recover the authoritative project state from the repository rather than relying on conversational history.

## Repository state

Stage 3G was merged to `main` by PR #15.

The project has progressed from reconstruction and accounting validation through causal feature materialization, held-out modeling, nonlinear interaction forensics, external temporal validation, and finally strict pre-event prediction.

The next agreed workstream is **Milestone 4A: Live Shadow Engine**.

## Scientific progression

### Reconstruction and provenance foundation

Earlier milestones established reproducible collection and reconstruction of the target Polymarket account's BTC 5-minute binary-market activity, FIFO complementary-pair accounting, bounded historical workflows, provenance, and CI-backed empirical artifacts.

The project deliberately separated accounting/reconstruction claims from predictive claims.

### Stage 3C — causal BTC feature panel

Stage 3C added independently collected Coinbase BTC/USD 60-second reference data and causal BTC features. Feature availability was constrained so reference information unavailable at an event timestamp could not leak into the feature vector.

### Stage 3D — transparent held-out baseline

Stage 3D established transparent linear/logistic held-out baselines and showed that timing plus inventory/execution state was materially more useful than BTC used as a simple linear standalone addition.

This became the transparent hurdle for later nonlinear work.

### Stage 3E — nonlinear held-out benchmark

Stage 3E froze shallow nonlinear models before observing their results.

The predeclared HGB timing+inventory primary candidate did not satisfy its complete advancement gate, although it improved weighted MAE. A secondary HGB all-feature ablation was much stronger: it improved weighted MAE on all seven discovery holdout days and Brier on six of seven relative to the transparent Stage 3D hurdle.

Because this was a secondary discovery, it was not promoted directly. It became the hypothesis tested in Stage 3F.

### Stage 3F — interaction forensics and external validation

Stage 3F tested whether the Stage 3E all-feature improvement was consistent with stable nonlinear BTC interactions or merely discovery-period structure.

On the untouched July 24–30, 2026 external period, the all-feature HGB candidate passed every frozen external-confirmation criterion.

Key external aggregate results:

- HGB all weighted MAE: approximately **0.16973**
- HGB timing+inventory weighted MAE: approximately **0.17550**
- transparent timing+inventory weighted MAE: approximately **0.17293**
- HGB all Brier: approximately **0.22311**
- HGB timing+inventory Brier: approximately **0.24967**
- transparent timing+inventory Brier: approximately **0.23960**
- HGB all MAE wins versus HGB timing+inventory: **6/7 external days**
- HGB all Brier wins versus HGB timing+inventory: **7/7 external days**

Held-out BTC permutation tests also supported the interpretation that BTC alignment contributed information. Joint BTC permutation degraded both MAE and Brier on all seven discovery days. `btc_return_60s` was the strongest individual BTC diagnostic.

The interaction evidence suggested that BTC state was most useful conditional on account inventory/execution state rather than as a standalone directional predictor.

### Stage 3G — strict pre-event prediction

Stage 3G moved the prediction boundary from contemporaneous forensic explanation to strict pre-event snapshots.

For every eligible FIFO complementary-pair event, features were reconstructed immediately **before** the execution that completed the pair. The completing execution could not mutate its own feature vector. Deterministic source ordering governed same-timestamp fills.

Forbidden inputs included target execution price/quantity/side effects, post-target fills, rolling activity containing the target, post-target inventory mutations, unavailable BTC reference data, and resolution information.

The previous pair lag was retained only as `lag_seconds_label_only` and excluded from prediction because it depends on knowing which execution completed the pair.

### Stage 3G frozen models

The frozen comparison was:

1. transparent pre-event timing + inventory baseline;
2. HGB pre-event timing + inventory;
3. HGB pre-event timing + inventory + `btc_return_60s`;
4. HGB pre-event timing + inventory + all usable causal BTC features.

No Stage 3G hyperparameter search was permitted.

Training/discovery remained August 7–13, 2026, 12:00–18:00 UTC.

The new untouched external validation period was July 10–16, 2026, 12:00–18:00 UTC.

## Stage 3G final empirical result

Stage 3G **PASSED** its frozen advancement gate.

The untouched July 10–16 external panel contained approximately **27,781 pre-event pair observations**.

External aggregate metrics:

| Model | Weighted MAE | Brier |
| --- | ---: | ---: |
| Linear timing + inventory | 0.17155 | 0.25062 |
| HGB timing + inventory | 0.16471 | 0.25177 |
| HGB timing + inventory + BTC 60s | 0.16138 | 0.23890 |
| **HGB all pre-event** | **0.15934** | **0.23137** |

The frozen primary HGB all-pre-event candidate beat HGB timing+inventory on:

- weighted MAE on **7/7 external days**;
- Brier on **7/7 external days**;
- aggregate weighted MAE;
- aggregate Brier.

It also beat the transparent pre-event baseline on both aggregate metrics.

The strict leakage/provenance audit passed.

All seven external days contained independently reportable eligible observations.

The single-feature `btc_return_60s` candidate also retained substantial pre-event value, while the full causal BTC family was strongest overall on the untouched external period.

## Current interpretation

The strongest statement supported by the evidence is:

> Information genuinely available before the pair-completing execution contains stable historical predictive information about the quality of the subsequent complementary execution, and causal BTC state improves prediction beyond pre-event timing and inventory/execution state alone across the frozen external validation period.

The project has therefore moved beyond purely contemporaneous forensic explanation.

However, the evidence remains historical and observational.

## What has NOT been proven

Do not claim that the current model establishes any of the following:

- live profitability;
- executable trading edge after fees;
- achievable fills at modeled prices;
- queue priority;
- acceptable live latency;
- resistance to signal decay;
- slippage or market-impact tolerance;
- robustness to API outages/data gaps;
- causal influence of BTC on the target account's decisions;
- production-safe automated trading.

Stage 3G explicitly earns prospective validation, not real-money deployment.

## Validated model to carry into Milestone 4A

The initial shadow model should be the **frozen Stage 3G HGB all-pre-event candidate** using the same feature definitions and model parameters used in the successful Stage 3G evaluation.

Do not retune it using live outcomes during the initial shadow-validation period.

`btc_return_60s` should remain a separately visible diagnostic because it carried substantial predictive information by itself in Stages 3F and 3G.

The existing Stage 3G materializer and leakage boundary are the reference implementation for online feature semantics.

## Milestone 4A — Live Shadow Engine objective

Build a functional prospective application that observes live data and reproduces the Stage 3G causal state in real time **without submitting orders**.

At minimum the engine should:

- ingest required live Polymarket market/trade state;
- ingest the required BTC reference feed;
- maintain deterministic account/inventory/execution state;
- construct the exact Stage 3G pre-event feature vector using only information available at scoring time;
- load and run the frozen Stage 3G model;
- timestamp every input, feature snapshot, prediction, and subsequent observed outcome;
- retain source/provenance metadata sufficient for replay and leakage auditing;
- record data latency, missing/stale inputs, scoring latency, and dropped/unscorable events;
- operate in shadow mode only: **no order creation, signing, submission, cancellation, or capital exposure**;
- produce prospective performance and calibration artifacts that can be compared with the historical Stage 3G expectations.

## Milestone 4A design principles

### Preserve the causal boundary

Online convenience must not weaken Stage 3G semantics. A feature unavailable at the scoring timestamp is unavailable, even if it arrives milliseconds later.

### Separate observation from execution

Milestone 4A is an observational/shadow system. Any future order-execution component must be a separately declared milestone with explicit execution, risk, and safety requirements.

### Record before judging

Predictions should be durably recorded before their outcomes are known. Do not retrospectively alter predictions or feature vectors.

### Make replay possible

Persist enough raw/provenance information to reproduce a shadow prediction deterministically offline.

### Treat failures as data

API latency, stale feeds, reconnects, missing BTC candles, ordering ambiguity, and dropped events must be recorded rather than silently hidden.

### Freeze before prospective evaluation

Define the initial shadow model, feature schema, scoring rules, success metrics, minimum observation horizon, and advancement criteria before prospective results are used to make model changes.

## Recommended Milestone 4A implementation sequence

1. Inspect current live-data/API capabilities and existing repository collectors.
2. Freeze `docs/MILESTONE_4A_LIVE_SHADOW_ENGINE_SPEC.md` before empirical shadow results.
3. Define online event contracts, timestamp semantics, stale-data policy, and deterministic ordering.
4. Implement live Polymarket and BTC adapters behind testable interfaces.
5. Implement an online state machine equivalent to Stage 3G pre-event semantics.
6. Add a frozen model artifact/training provenance mechanism.
7. Implement shadow scoring and append-only prediction logging.
8. Add deterministic replay tests comparing online and offline feature construction.
9. Add operational health/latency/data-quality telemetry.
10. Run locally/CI against fixtures and bounded replay before enabling live observation.
11. Begin a separately declared prospective observation period with no model tuning during the frozen evaluation window.

## Neural-network work

A neural-network challenger is deliberately deferred.

The historical evidence is now strong enough that prospective validation is more informative than adding model complexity. A small neural network may later compete against HGB under a separately frozen protocol, but it should not delay Milestone 4A.

## Source of truth

For exact implementation details, consult the repository specifications and code for Stages 3C–3G, especially:

- Stage 3F interaction-forensics specification and implementation;
- `docs/MILESTONE_3G_PRE_EVENT_PREDICTION_SPEC.md`;
- Stage 3G pre-event materializer;
- Stage 3G leakage audit;
- Stage 3G model/evaluation code;
- Stage 3G workflow and final empirical artifact.

If this handoff conflicts with executable code or a frozen stage specification, investigate the discrepancy before proceeding rather than silently choosing one interpretation.

## Immediate next action

Begin **Milestone 4A: Live Shadow Engine** by inspecting `main`, then freeze the Milestone 4A architecture/evaluation specification before implementing live behavior.
