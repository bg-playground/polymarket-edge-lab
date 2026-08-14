# Empirical Pair Sensitivity and Latency Analysis

## Purpose

This phase extends the merged Milestone 2 forensic work without beginning Milestone 3 strategy inference. The goal is to explain the bounded-cohort result from PR #6 and test whether the public claim of an average complete-set cost near 98.43c is supported under any predeclared, economically defensible accounting convention.

The current bounded reference result is chronological FIFO BUY-lot matching over fully contained BTC 5-minute markets. In the validated six-hour cohort it produced a quantity-weighted pair cost of 102.6472c and an implied gross edge of -2.6472c. This phase must not optimize matching to manufacture a lower number.

## Scope

Use the existing bounded cohort definition: observed `btc-updown-5m-<epoch>` markets whose complete `[start, start+300)` interval lies inside the collection interval. Preserve the existing rule that markets containing SELL fills are excluded from BUY-lot pair-cost accounting unless a later explicitly documented method is implemented.

Implement the following analyses.

### 1. Accounting-definition sensitivity

Report all definitions side by side over the exact same eligible cohort and fills:

- FIFO complementary BUY-lot matching: retain as the primary historical lot-matching baseline.
- LIFO complementary BUY-lot matching: sensitivity only.
- Weighted-average inventory accounting at each incremental increase in paired inventory. This must use only inventory and cost known at that timestamp; no future information.
- Optional theoretical lower/upper matching bounds may be included only if clearly labeled non-realized sensitivity and never used as the headline result.

For every method report quantity-weighted pair cost, gross edge `1 - pair_cost`, paired quantity, share quantity below $1.00, pair-fragment/event count, and market count.

### 2. Per-market distributions

For each eligible market report at minimum:

- market/condition ID and slug;
- market start/end epoch;
- included fill count;
- total paired quantity;
- quantity-weighted pair cost under each supported accounting method;
- implied gross edge;
- fraction of paired quantity below $1.00;
- ending UP shares, DOWN shares, paired shares, and directional residual shares where available.

Produce aggregate distribution statistics across markets: count, quantity-weighted mean, unweighted mean, median, p10, p25, p75, p90, min, max. Clearly distinguish market-weighted from share-quantity-weighted statistics.

### 3. Complementary-fill latency analysis

For pair-formation events, classify the observed lag between the two complementary fills into fixed buckets:

- 0 seconds
- 1 second
- 2-5 seconds
- 6-15 seconds
- 16-30 seconds
- 31-60 seconds
- 61-120 seconds
- >120 seconds

For each bucket report paired quantity, percentage of total paired quantity, quantity-weighted pair cost, implied gross edge, and percentage of paired quantity below $1.00.

Because public API timestamps are one-second resolution, preserve the existing within-second ordering sensitivity and do not imply sub-second sequence certainty.

### 4. Time-within-market analysis

For each pair-formation event calculate seconds elapsed from the market's start timestamp and classify it into fixed 30-second buckets across the 300-second market lifetime: `[0,30)`, `[30,60)`, ..., `[270,300)`.

For each bucket report paired quantity, quantity-weighted pair cost, gross edge, and percentage formed below $1.00.

Also report early/middle/late summary bands: 0-99 seconds, 100-199 seconds, 200-299 seconds.

### 5. Transaction-hash grouping diagnostic

Do not assume a transaction hash equals an order. Measure and report:

- distinct transaction hashes;
- fills per transaction hash distribution;
- paired UP/DOWN activity sharing the same transaction hash;
- quantity-weighted pair cost for complementary BUY fills that can be paired within the same transaction hash under a deterministic rule.

Label this as a diagnostic, not a replacement for chronological accounting.

### 6. Public-claim comparison

Compare the public 98.43c pair-cost / +1.57c gross-edge claim against every predeclared accounting method and major latency/time bucket. A result is not considered support merely because one narrow bucket happens to be near the claimed value.

The human-readable report should answer:

1. Does any standard accounting definition put the full bounded cohort near 98.43c?
2. Are profitable pairs concentrated at particular complementary-fill lags?
3. Are profitable pairs concentrated at particular times within the 5-minute market?
4. Does same-transaction activity materially differ from all chronological pair formation?
5. Is the discrepancy with the public claim robust across reasonable accounting choices?

## Data integrity requirements

- Use Decimal for prices, quantities, cost, and edge.
- Never use future information to improve historical pair cost.
- Never discard expensive pair events merely because they reduce apparent performance.
- Keep cohort and inclusion rules identical across methods.
- Preserve traceability from aggregate results to pair events and normalized fills.
- Make bucket boundaries explicit and tested.
- Report zero/empty buckets rather than silently omitting them where practical.
- Do not infer maker/taker intent, strategy, signals, or profitability beyond measured execution-price accounting.

## Outputs

Add machine-readable and human-readable outputs under a clear analysis/report directory. At minimum produce:

- accounting-method comparison JSON and Markdown;
- per-market metrics JSON/CSV or Parquet;
- latency-bucket metrics JSON/CSV or Parquet;
- time-within-market metrics JSON/CSV or Parquet;
- transaction-hash diagnostic JSON/Markdown;
- enough event-level output to audit aggregate calculations.

Integrate these outputs into the bounded GitHub Actions workflow artifact.

## Testing

Add deterministic tests covering at minimum:

- FIFO vs LIFO producing intentionally different results;
- weighted-average incremental pair accounting with partial lot matches;
- no use of future fills;
- all latency bucket boundaries;
- all market-time bucket boundaries;
- quantity-weighted versus unweighted aggregation;
- same-transaction pairing diagnostic;
- one-second timestamp ties and ordering sensitivity;
- empty buckets/markets and Decimal precision.

CI must remain green: ruff check, ruff format, mypy, and pytest.

## Out of scope

Do not add LangGraph, LLM agents, neural networks, predictive ML, market-price forecasting, underlying BTC signal inference, strategy optimization, backtesting, order placement, wallet signing, or live trading. Those belong to a later milestone only after this empirical phase is reviewed and merged.

## Definition of done

This phase is complete when the same bounded real-data cohort can be rerun reproducibly and the resulting report explains how pair cost changes across FIFO, LIFO, weighted-average accounting, latency, market-time, and transaction-hash diagnostics without cherry-picking or claiming more than the public data supports.
