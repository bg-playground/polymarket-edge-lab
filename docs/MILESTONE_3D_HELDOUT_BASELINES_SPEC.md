# Milestone 3D — Held-out Explanatory Baselines

## Purpose

Stage 3C produced a validated causal seven-day feature panel for `nagi777`. Stage 3D measures how much held-out explanatory value is contributed by timing, account inventory/execution state, and contemporaneous BTC state before any nonlinear tree or neural-network work.

This phase is historical research only. It does not authorize live trading, order placement, wallet signing, capital allocation, or claims of future profitability.

## Frozen panel

Rebuild and reuse the same seven independent UTC windows used by Stages 3B/3C:

- 2026-08-07 through 2026-08-13;
- 12:00–18:00 UTC each day;
- FIFO pair-formation events in fully contained BTC five-minute markets;
- same account, collection, ledger, pairing, and causal BTC alignment rules as Stage 3C.

No date may be removed or replaced because of Stage 3D results.

## Interpretation boundary

Stage 3C features are causal in the sense that they never use information after the pair-formation timestamp. However, some cumulative price/VWAP inventory fields include the execution that forms the pair itself. Therefore Stage 3D is explicitly a **held-out regime-explanation study**, not a deployable pre-trade prediction study.

The primary inventory feature set excludes:

- `cumulative_up_vwap`;
- `cumulative_down_vwap`;
- `implied_complete_set_cost`.

Those fields remain available for retrospective diagnostics only.

## Primary targets

Continuous target:

- `pair_cost`.

Binary target:

- `favorable = pair_cost < 1.00`.

Quantity weights use `paired_shares`.

## Feature families

### Timing

- complementary-fill lag;
- elapsed seconds within the five-minute market;
- seconds remaining.

### Inventory/execution

Quantity and activity state only for the primary comparison: UP/DOWN inventory, paired/residual inventory, imbalance, time since side fills, trailing fill counts and quantities, side switching, cumulative paired quantity, and same-second fill count.

### BTC

Only fields genuinely supported by the achieved 60-second Coinbase resolution:

- 60-second return;
- 120-second return;
- absolute 60-second return;
- return since market start;
- range since market start.

Do not use unavailable 15s/30s return fields or realized-volatility fields.

## Frozen comparisons

Evaluate all of the following without post-result feature-set changes:

1. global quantity-weighted mean/rate;
2. frozen timing-bucket baseline;
3. timing linear/logistic model;
4. inventory linear/logistic model;
5. BTC linear/logistic model;
6. timing + inventory;
7. timing + BTC;
8. inventory + BTC;
9. all usable primary features.

## Models

Use transparent regularized models only:

- Ridge regression for `pair_cost`;
- logistic regression for `favorable`.

Within every held-out fold, median imputation and standardization must be fitted only on training windows. Sample weighting uses paired quantity.

No hyperparameter search is authorized. Fixed regularization values are used to avoid tuning to seven historical days.

## Validation

Use leave-one-calendar-window-out validation: six days train, one full day tests. Report every held-out day separately and arithmetic means across the seven folds.

Primary regression metric:

- paired-share-weighted MAE.

Secondary regression metrics:

- unweighted MAE;
- paired-share-weighted bias.

Primary classification metric:

- paired-share-weighted Brier score.

Secondary classification metric:

- paired-share-weighted log loss.

## Incremental-value rule

Timing is the primary reference model. For every feature family and combination, report the difference in weighted MAE and Brier score versus the timing-only regularized model.

Negative deltas mean improvement. A feature family should not be described as adding robust explanatory value merely because its seven-fold average improves. Its per-day pattern must also be inspected for concentration in one or two windows.

## Guardrails

- no random row splits;
- no date selection after observing results;
- no hyperparameter search;
- no unavailable BTC features;
- no contemporaneous cumulative price/VWAP fields in primary models;
- no tree models, boosting, neural networks, LangGraph, or agents in this phase;
- no trading or profitability claims.
