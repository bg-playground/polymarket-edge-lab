# Milestone 3 — Regime Analysis and Interpretable Feature Modeling

## Purpose

Milestone 3 begins only after the timing-robustness phase replicated both frozen historical timing effects across seven independent six-hour windows. The objective is now to explain **why pair-formation economics vary by regime** and determine whether observable market-state features can distinguish favorable from unfavorable historical conditions without leakage or post-hoc bucket tuning.

This milestone is analytical and research-only. It does not authorize live trading, order placement, wallet signing, autonomous execution, or production strategy deployment.

## Core research question

What observable information available at or before a pair-formation event explains variation in historical complementary UP/DOWN acquisition cost, especially the transition between windows with strongly sub-$1 FIFO pair cost and windows near or above $1?

## Primary outcomes

Milestone 3 should produce:

1. a deterministic feature table aligned to the existing canonical ledger and FIFO pair events;
2. regime labels defined from historical execution-price accounting, not future market outcome;
3. interpretable baseline models that quantify which features are associated with favorable pair formation;
4. walk-forward / date-held-out evaluation that prevents random train/test leakage across adjacent 5-minute markets;
5. feature importance and ablation results showing whether timing alone explains the effect;
6. calibration and stability diagnostics across independent days/windows;
7. a documented conclusion about whether the regime signal is sufficiently stable to justify a later strategy-simulation milestone.

## Stage 3A — Feature reconstruction

Build features using only information observable at or before the timestamp being analyzed.

### Trader / inventory state

At each FIFO pair event or decision timestamp, reconstruct:

- current UP inventory;
- current DOWN inventory;
- paired inventory;
- residual directional inventory;
- normalized inventory imbalance;
- cumulative UP VWAP to timestamp;
- cumulative DOWN VWAP to timestamp;
- current implied complete-set cost from inventory VWAPs where defined;
- time since last UP fill;
- time since last DOWN fill;
- recent fill count and quantity over fixed trailing windows;
- recent side-switch frequency;
- cumulative paired quantity within the market;
- fraction of eventual observed market paired quantity already formed **only as a retrospective diagnostic, never as a predictive feature**.

### Polymarket execution / market state

Where public data permits, reconstruct contemporaneous:

- UP and DOWN trade prices;
- spread/proxy spread if valid historical quotes are available;
- recent trade-price volatility;
- short-horizon momentum of UP probability proxy;
- distance of UP + DOWN observed execution prices from $1;
- recent paired-cost trend;
- market elapsed seconds;
- seconds remaining in the five-minute market;
- recent execution intensity;
- transaction-hash clustering diagnostics;
- same-second fill density.

If historical order-book snapshots are not available from a reliable source, do not fabricate them. Use execution-derived proxies and document the limitation.

### Underlying BTC state

Add an independently sourced BTC spot/perpetual reference series with timestamps aligned in UTC. Prefer a liquid exchange/public API with reproducible historical candles or trades.

Candidate features at event time:

- BTC return over 5s / 15s / 30s / 60s / 120s;
- realized volatility over matching trailing intervals;
- absolute return / movement magnitude;
- distance from BTC price at market start;
- direction since market start;
- acceleration / change in short-horizon return;
- range since market start.

All BTC features must use only observations timestamped at or before the feature row. No future candle close may leak into a row.

## Stage 3B — Targets and regime definitions

Use multiple target formulations so conclusions do not depend on one arbitrary label.

### Regression target

Primary continuous target:

- FIFO pair-event cost (`UP acquisition price + DOWN acquisition price`) for the newly formed paired quantity.

Optional weighted target:

- quantity-weight observations by paired shares, while retaining unweighted diagnostics.

### Classification targets

Predeclare thresholds before model fitting:

- favorable: pair cost < 1.00;
- strong favorable: pair cost <= 0.98;
- unfavorable: pair cost >= 1.00.

A secondary window-level regime label may classify a six-hour window as favorable when its quantity-weighted FIFO full-cohort pair cost is < 1.00, but event-level and window-level targets must never be mixed in the same evaluation without explicit hierarchical treatment.

## Stage 3C — Baselines before ML

Before any machine learning model, fit transparent baselines:

1. timing-only rule set using elapsed market time and complementary-fill lag;
2. simple linear / logistic model with timing variables only;
3. timing + inventory state;
4. timing + BTC state;
5. timing + inventory + BTC state.

The purpose is to measure incremental explanatory value. A complex model is not useful if it merely rediscovers the 61–120s lag and 100–199s market-time findings.

## Stage 3D — Interpretable ML

Authorized models for this milestone:

- regularized linear regression;
- logistic regression;
- shallow decision tree;
- random forest or gradient-boosted trees with conservative depth/regularization;
- optionally a small multilayer perceptron only after tabular baselines and leakage checks are complete.

A neural network is **not** the default. It may be added only as a benchmark after simpler models establish a stable signal.

Do not use LLM agents or LangGraph for statistical prediction. Agent orchestration may later help coordinate research tasks, but it must not obscure feature lineage, target construction, or evaluation.

## Validation design

Random row-level splits are prohibited for claim-grade evaluation.

Use chronological/date-grouped evaluation such as:

- leave-one-day-out;
- rolling train -> future-day test;
- expanding-window walk-forward.

At minimum, every reported model must be tested on calendar days not used for fitting.

Report both quantity-weighted and unweighted metrics when materially different.

### Regression metrics

- MAE;
- RMSE;
- weighted MAE;
- rank correlation where useful;
- error by day/window;
- error by timing bucket.

### Classification metrics

- ROC-AUC as secondary;
- PR-AUC when class imbalance matters;
- Brier score;
- calibration curve / calibration bins;
- precision/recall at predeclared thresholds;
- confusion matrix by held-out day.

Do not optimize thresholds on the same held-out set used to report final performance.

## Leakage guardrails

Strictly prohibit features containing information from after the prediction timestamp, including:

- eventual market winner;
- settlement result;
- future BTC movement;
- later trader fills;
- eventual total market inventory;
- future paired quantity;
- market-end VWAP;
- final residual inventory;
- any forward-looking aggregate computed across the full five-minute market.

Add deterministic tests that deliberately inject future rows and verify current features do not change.

## Feature lineage

Every feature column must have documented:

- definition;
- source;
- timestamp semantics;
- lookback window;
- null behavior;
- whether it is permitted for predictive modeling or retrospective diagnostics only.

Produce a machine-readable feature manifest.

## Ablation plan

Run fixed model families on these predeclared feature groups:

1. timing only;
2. inventory only;
3. BTC only;
4. timing + inventory;
5. timing + BTC;
6. inventory + BTC;
7. all authorized features.

The key question is whether non-timing features improve held-out performance consistently across days.

## Regime interpretation

Produce per-day/per-window summaries linking feature distributions to FIFO economics. Specifically examine the contrast between historically favorable windows and the near/breakeven windows observed in the robustness work.

Use descriptive statistics and interpretable model outputs to answer:

- Is favorable pair formation associated with higher BTC movement/volatility?
- Does inventory imbalance precede cheap complementary fills?
- Does fill intensity or side-switching change by regime?
- Are favorable periods concentrated in specific market-time regions after controlling for other features?
- Do the same relationships hold on held-out days?

These are hypotheses to test, not assumptions.

## Outputs

Generate reproducible artifacts containing:

- source-data manifest;
- feature manifest;
- feature table (or bounded sample if too large, with full artifact retained externally in Actions);
- leakage-test report;
- per-day descriptive regime report;
- baseline model results;
- ablation table;
- walk-forward / leave-one-day-out metrics;
- calibration diagnostics;
- feature importance / coefficient tables;
- model cards describing limitations;
- Markdown research summary.

Large datasets and fitted model binaries should be GitHub Actions artifacts rather than committed to git unless small and deterministic.

## Definition of done

Milestone 3 is complete when:

- feature generation is deterministic and timestamp-safe;
- BTC alignment is validated and documented;
- no predictive feature uses future information;
- timing-only baselines are established;
- inventory and BTC feature groups are evaluated incrementally;
- at least one interpretable model family is evaluated with date-held-out testing;
- all ablations are reported, including negative results;
- model performance is stable enough to characterize, or instability is clearly demonstrated;
- the project can make a defensible decision on whether a later simulation/backtesting milestone is warranted.

## Still prohibited

Milestone 3 does not authorize:

- live trading;
- order placement;
- wallet signing;
- private-key handling;
- autonomous execution;
- capital allocation recommendations;
- claiming future profitability from historical model performance;
- optimization against a live account;
- automated deployment of a discovered rule.
