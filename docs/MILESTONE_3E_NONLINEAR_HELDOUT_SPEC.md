# Milestone 3E: constrained nonlinear held-out benchmark

## Purpose

Stage 3D found that transparent timing + inventory models materially outperformed timing-only
baselines across the frozen seven-day panel, while BTC-only and timing + BTC did not add value.
Stage 3E asks one narrower question:

> Does shallow nonlinear structure in the same causal/contemporaneous feature panel add stable
> held-out explanatory value beyond the transparent Stage 3D timing + inventory Ridge/logistic
> baseline?

This remains a historical regime-explanation experiment. It is not a live trading, execution, or
future-profit claim.

## Frozen panel and folds

- Rebuild the same seven windows used by Stages 3C and 3D: 2026-08-07 through 2026-08-13,
  12:00-18:00 UTC.
- Reuse the Stage 3C causal panel materializer without changing FIFO accounting or BTC alignment.
- Hold out one complete calendar window at a time: six train, one test.
- Never use random row splits.
- Sample weights remain paired shares.

## Hurdle model

The frozen hurdle is the Stage 3D `timing_inventory` model:

- Ridge(alpha=1.0) for pair cost.
- LogisticRegression(C=1.0, max_iter=2000) for pair cost < $1.
- Training-fold-only median imputation and scaling.
- Timing + primary inventory/execution features only.

The hurdle is recomputed on the exact Stage 3E panel so comparisons share identical rows and folds.

## Nonlinear candidates

No hyperparameter search is permitted.

### Primary: `hgb_timing_inventory`

HistGradientBoosting regression/classification using the Stage 3D timing + inventory features:

- max_depth=3
- learning_rate=0.05
- max_iter=100
- min_samples_leaf=100
- l2_regularization=1.0
- random_state=0
- training-fold-only median imputation

### Interpretability benchmark: `tree_timing_inventory`

Decision-tree regression/classification on timing + inventory:

- max_depth=3
- min_samples_leaf=100
- random_state=0
- training-fold-only median imputation

### Ablations

- `hgb_inventory`: same fixed HGB parameters, inventory features only.
- `hgb_all`: same fixed HGB parameters, timing + inventory + usable BTC features.

The `hgb_all` ablation tests whether nonlinear interactions rescue incremental BTC information. It is
secondary; BTC is not promoted to a primary feature family based on in-sample fit.

## Metrics

Regression:

- paired-share-weighted MAE (primary)
- unweighted MAE
- paired-share-weighted bias

Classification:

- paired-share-weighted Brier score (primary)
- paired-share-weighted log loss

Report every metric for every held-out day and the arithmetic mean across the seven folds.

## Advancement gate

The primary `hgb_timing_inventory` model earns a Stage 3F complexity discussion only if all four
conditions hold:

1. Mean weighted MAE is lower than the Stage 3D timing + inventory hurdle.
2. Mean Brier score is lower than the hurdle.
3. Weighted MAE improves on at least 4 of 7 held-out days.
4. Brier score improves on at least 4 of 7 held-out days.

Failure of this gate is a valid negative result and must be preserved. Do not tune dates,
hyperparameters, feature families, or thresholds after seeing the result.

## Feature-policy guardrail

Primary inventory features continue to exclude cumulative UP/DOWN VWAP and implied complete-set
cost because those include the pair-forming execution itself. The Stage 3D caveat remains: some
inventory state is contemporaneous with the pair event, so this is explanatory evidence rather than
a strict pre-event deployable prediction test.
