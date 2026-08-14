# Milestone 3B — Historical Feature Panel and Transparent Baselines

## Purpose

Stage 3A established timestamp-safe Polymarket/inventory feature reconstruction and causal BTC candle alignment. Stage 3B turns those primitives into a reproducible historical feature panel over the same independent study windows used by the timing-robustness phase, then evaluates transparent baselines before any tree model or neural network.

This phase is research-only. It does not authorize live trading, order placement, wallet signing, autonomous execution, capital allocation, or claims of future profitability.

## Primary questions

1. Do timing variables alone explain most variation in FIFO pair-formation cost?
2. Does contemporaneous inventory/execution state add held-out explanatory value beyond timing?
3. Does independently sourced BTC state add held-out explanatory value beyond timing and inventory?
4. Are relationships stable across calendar-day holdouts, or concentrated in one or two historical windows?

## Frozen study panel

Reuse the seven independent six-hour UTC windows from the merged timing-robustness study. Do not replace unfavorable windows or tune date selection after observing Stage 3B results.

Each feature row corresponds to an existing FIFO pair-formation event in a complete BTC 5-minute market. Preserve `window_id`, market identifiers, event timestamp, paired quantity, pair cost, and source provenance.

## BTC reference data

Use an independently sourced public BTC/USD or BTC/USDT historical trade/candle feed with documented provenance and UTC timestamp semantics.

Requirements:

- obtain sufficient granularity to support the Stage 3A 15s/30s/60s/120s features;
- preserve raw responses or source files in workflow artifacts;
- record provider, symbol, endpoint/dataset, retrieval timestamp, requested bounds, and observed bounds;
- never interpolate from future observations;
- if exact one-second data are unavailable, document the achieved resolution and disable features whose semantics cannot be honored honestly;
- a candle is usable only after its close timestamp is observable;
- missing reference history produces nulls rather than future-filled values.

## Feature table

Join the Stage 3A regime features with causal BTC features and include explicit group labels from `docs/MILESTONE_3_FEATURE_MANIFEST.json`.

Required outputs:

- Parquet feature table;
- CSV summary/sample suitable for inspection;
- machine-readable feature manifest/provenance;
- per-window coverage and null-rate report;
- target distribution by window;
- quantity-weighted and unweighted descriptive summaries.

## Targets

Primary continuous target:

- `pair_cost`.

Secondary descriptive classification targets:

- `favorable = pair_cost < 1.00`;
- `strong_favorable = pair_cost <= 0.98`.

Classification targets must not replace the continuous target when summarizing economics.

## Predeclared feature-group ablations

Evaluate exactly these groups before any complex model:

1. timing only;
2. inventory only;
3. BTC only;
4. timing + inventory;
5. timing + BTC;
6. inventory + BTC;
7. all features.

Do not add/remove groups after observing results merely to improve performance.

## Transparent baselines

Implement deterministic baselines first:

- global training-fold quantity-weighted mean pair cost;
- timing-bucket baseline using only training-fold data and the already frozen timing definitions;
- regularized linear regression for pair cost;
- regularized logistic regression for `favorable` only after the continuous baseline is reported.

Model preprocessing must be fitted on training dates only. Null imputation/scaling must not inspect held-out dates.

## Evaluation

Primary evaluation is leave-one-calendar-day-out across the seven frozen windows. Random row-level train/test splits are prohibited for claim-grade results.

For every held-out day and feature group report, where applicable:

- quantity-weighted MAE for pair cost;
- unweighted MAE;
- quantity-weighted mean prediction error/bias;
- weighted R-squared or an explicitly documented alternative;
- classification log loss and Brier score for `favorable`;
- calibration summary;
- row count and paired-share weight.

Also report pooled held-out metrics and the distribution across held-out days. A feature group is not considered stable merely because its pooled metric improves if most individual days degrade.

## Leakage and invariance requirements

- Preserve Stage 3A future-fill and future-BTC invariance tests.
- Add a panel-level test proving that appending future source observations cannot change already-materialized historical feature rows.
- Training-fold preprocessing must be tested so held-out values cannot influence imputation/scaling.
- Retrospective-only fields in the manifest must never enter a model matrix.

## Interpretation rules

Stage 3B is explanatory historical analysis, not a tradable-strategy claim.

A feature group may be described as adding held-out explanatory value only if its improvement over the relevant simpler baseline is visible in pooled metrics and is not dependent on a single held-out day.

Negative or unstable results must be retained.

## Definition of done

Stage 3B is complete when:

1. all CI checks pass;
2. the seven-window feature panel is reproducibly materialized;
3. BTC provenance and achieved resolution are explicit;
4. feature/null coverage is reported per window;
5. all seven predeclared ablations are evaluated with date-held-out folds;
6. timing-only and global-mean baselines are included;
7. leakage/preprocessing invariance tests pass;
8. machine-readable and human-readable reports are preserved as workflow artifacts;
9. results state clearly whether inventory and/or BTC features add stable held-out explanatory value;
10. no live-trading capability is introduced.
