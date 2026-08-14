# Empirical Timing Robustness Phase

## Purpose

This phase tests whether the timing patterns observed in the merged six-hour BTC 5-minute cohort are persistent across a materially larger, non-overlapping sample. It remains pre-Milestone-3: the goal is robustness and replication, not strategy inference, prediction, optimization, backtesting, or live trading.

The reference bounded cohort showed full-cohort pair cost above $1 under FIFO/LIFO/weighted-average accounting, while certain descriptive timing slices were below $1, especially 61-120 second complementary-fill lag and the 100-199 second portion of the 5-minute market. These effects must now be tested out-of-sample.

## Primary questions

1. Does the 61-120 second FIFO latency bucket remain below $1 across multiple independent windows?
2. Does the 100-199 second market-time band remain below $1 across multiple independent windows?
3. Are the signs and magnitudes stable by day/window, or driven by one unusual interval?
4. Does the full-cohort result remain above $1 under FIFO, LIFO, and incremental weighted-average accounting?
5. How much paired quantity is required before the timing estimates stabilize?

## Dataset design

Use the verified `nagi777` account and the existing maker-inclusive public Data API collector.

Run a reproducible multi-window study using non-overlapping UTC intervals. Prefer at least:

- 7 distinct calendar days when public history permits;
- 6 hours per day, for at least 42 hours total;
- the same hour-of-day window across days for the primary panel to reduce time-of-day confounding;
- an optional second panel using different hours only as a separately labeled sensitivity.

If API/history constraints prevent the target design, report the exact achieved window count, hours, market count, fill count, and reasons for missing windows. Never silently substitute overlapping periods.

Only fully contained observed `btc-updown-5m-<epoch>` markets may enter claim-grade timing analysis. Preserve the existing exclusion rule for markets containing SELL fills unless an explicitly documented SELL-aware method is added later.

## Predeclared analyses

For every window and for the pooled sample, compute the existing metrics without changing definitions:

- FIFO complementary BUY-lot pair formation;
- LIFO sensitivity;
- incremental weighted-average paired-inventory accounting;
- fixed latency buckets: 0s, 1s, 2-5s, 6-15s, 16-30s, 31-60s, 61-120s, >120s;
- fixed 30-second market-time buckets;
- early/middle/late bands: 0-99, 100-199, 200-299 seconds;
- transaction-hash diagnostic;
- same-second ordering sensitivity.

Do not redefine buckets after seeing results.

## Robustness statistics

For the two primary timing hypotheses (61-120s latency and 100-199s market-time band), report:

- per-window paired quantity;
- per-window quantity-weighted pair cost and gross edge;
- share of paired quantity below $1;
- number and fraction of windows with pair cost below $1;
- pooled quantity-weighted pair cost;
- equal-window mean pair cost;
- median window pair cost;
- min/max and p25/p75 across windows;
- paired-quantity concentration by window;
- leave-one-window-out pooled estimates;
- cumulative estimates as windows are added chronologically.

Use deterministic bootstrap confidence intervals only if implemented transparently with a fixed seed and resampling at the market or window level. Do not use fill-level bootstrap that assumes fills are independent.

## Multiple-comparison guardrail

The primary hypotheses are fixed before the run:

1. latency bucket 61-120s;
2. market-time band 100-199s.

All other buckets remain descriptive secondary analyses. A secondary bucket that looks attractive after expansion must not be promoted to a primary finding without a new out-of-sample phase.

## Stability classifications

For each primary hypothesis, classify the expanded result conservatively:

- `replicated`: pooled pair cost < $1, at least 60% of adequately sized windows < $1, and leave-one-window-out estimates remain < $1;
- `mixed`: pooled result < $1 but window consistency or leave-one-out robustness fails;
- `not_replicated`: pooled result >= $1;
- `insufficient_data`: fewer than 4 adequately sized independent windows or material completeness problems.

An `adequately sized` window must have at least 500 paired shares in the target slice, unless the implementation documents a stricter threshold before running the study.

These classifications describe historical execution-price accounting only; they are not claims of future profitability.

## Outputs

Produce machine-readable and Markdown outputs with:

- manifest of every requested and achieved collection window;
- per-window completeness evidence;
- per-window cohort/fill/market counts;
- per-window full-cohort accounting metrics;
- per-window latency and market-time metrics;
- pooled metrics;
- primary-hypothesis robustness table;
- leave-one-window-out results;
- cumulative stability results;
- secondary descriptive bucket tables;
- limitations and any data-quality anomalies.

Include outputs and raw/normalized evidence in a GitHub Actions artifact. Avoid committing large live datasets to git.

## Testing

Add deterministic tests covering:

- non-overlapping window generation;
- exact UTC boundaries;
- completeness propagation across windows;
- pooled quantity-weighted versus equal-window means;
- adequate-window threshold behavior;
- replication/mixed/not-replicated/insufficient-data classifications;
- leave-one-window-out calculations;
- cumulative calculations;
- missing/incomplete windows;
- Decimal precision.

CI must remain green: ruff check, ruff format --check, mypy, pytest.

## Out of scope

Do not add predictive features, BTC price signals, neural networks, ML, LangGraph, LLM agents, strategy optimization, simulated trading, backtesting, order placement, wallet signing, or live trading.

## Definition of done

This phase is complete when the same predeclared timing hypotheses have been evaluated across a materially larger set of independent windows, with reproducible completeness evidence and conservative robustness classifications, and when the result tells us whether the timing effect is persistent enough to justify beginning Milestone 3.