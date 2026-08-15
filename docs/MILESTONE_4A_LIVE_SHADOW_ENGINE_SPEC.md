# Milestone 4A — Live Shadow Engine

## Status

**Frozen before prospective Milestone 4A shadow results are observed.**

This specification defines the first prospective, no-capital validation of the Stage 3G strict pre-event model. The implementation may change only to satisfy this frozen contract, correct an objective defect, or address an external API incompatibility. Any change that could affect feature values, prediction timing, label binding, model outputs, evaluation inclusion, or advancement criteria requires a new explicitly versioned specification and restarts the affected prospective evaluation window.

## Motivation

Stage 3G passed its strict pre-event external validation gate using features reconstructed immediately before the fill that completed an eligible FIFO complementary pair. The frozen primary candidate, HGB timing + inventory + all usable causal BTC features, beat both the HGB timing+inventory comparator and the transparent pre-event baseline on aggregate weighted MAE and Brier, and on all seven untouched external days.

Stage 3G therefore supports progression to prospective observation, but it remains historical and observational. Milestone 4A exists to test whether the exact causal feature semantics and frozen model can be maintained prospectively under real API latency, missing data, reconnects, source-ordering ambiguity, and data-arrival delays.

Milestone 4A does **not** submit, sign, cancel, simulate-submit, or route orders.

## Claims permitted

A successful Milestone 4A may support statements about:

- prospective shadow predictive performance;
- prospective calibration;
- stability of the Stage 3G feature/model relationship under live data arrival;
- online/offline feature parity;
- observable source latency and data-quality behavior;
- deterministic replay of live shadow decisions;
- operational feasibility of maintaining the causal state machine without capital exposure.

Milestone 4A does **not** establish:

- executable profitability;
- achievable order fills;
- queue position;
- expected profit after fees;
- slippage or market impact;
- production trading safety;
- acceptable execution latency;
- robustness of any future order-routing component;
- causal influence of BTC on another account's decisions.

Any execution-capable system is a later separately frozen milestone.

## Frozen target account and market domain

The observed account remains the Stage 3G target account:

`0xbf337426aa856996b8bb79b238345dd1a0276bf7`

The primary evaluation domain remains eligible BTC 5-minute binary markets under the existing repository market-classification and FIFO complementary-pair accounting rules.

The primary prospective evaluation window is restricted to **12:00–18:00 UTC** each evaluation day, matching the Stage 3G discovery and external-validation clock-time domain. The engine may record out-of-window observations for diagnostics, but they must not enter the frozen Milestone 4A advancement gate.

## Frozen model family

The primary model is the Stage 3G **`hgb_all_pre_event`** candidate.

The implementation must use the exact Stage 3G primary feature order:

1. `elapsed_seconds`
2. `seconds_remaining`
3. `up_inventory`
4. `down_inventory`
5. `paired_inventory`
6. `residual_inventory`
7. `inventory_imbalance`
8. `seconds_since_last_up_fill`
9. `seconds_since_last_down_fill`
10. `fill_count_15s`
11. `fill_count_30s`
12. `fill_count_60s`
13. `fill_qty_15s`
14. `fill_qty_30s`
15. `fill_qty_60s`
16. `side_switches_60s`
17. `cumulative_paired_quantity`
18. `same_second_fill_count`
19. `btc_return_60s`
20. `btc_return_120s`
21. `btc_absolute_return_60s`
22. `btc_return_since_market_start`
23. `btc_range_since_market_start`

The HGB regression and classification parameters remain exactly those used in Stage 3E/3G:

- `learning_rate=0.05`
- `max_depth=3`
- `max_iter=100`
- `min_samples_leaf=100`
- `l2_regularization=1.0`
- `random_state=0`
- median imputation before HGB
- training sample weights equal to `paired_shares`

The frozen training data is the complete Stage 3G August 7–13, 2026 discovery panel, 12:00–18:00 UTC each day. Live outcomes must never be used to refit, reweight, calibrate, select features, alter thresholds, or modify preprocessing during the initial Milestone 4A evaluation window.

Before live observation begins, the serialized regression and classification artifacts must record at minimum:

- model family and exact parameters;
- exact ordered feature list;
- training-window manifest;
- repository commit used to train the artifact;
- Python and scikit-learn versions;
- artifact SHA-256 hashes;
- training row count and total training `paired_shares` weight;
- imputer statistics fingerprint or equivalent serialized preprocessing fingerprint.

A model artifact whose fingerprint changes during the frozen prospective window invalidates that window.

## Frozen comparators and diagnostics

For the same prospective snapshots, retain the following frozen Stage 3G comparators:

1. `hgb_timing_inventory`;
2. `linear_timing_inventory`;
3. `hgb_timing_inventory_btc60` as a diagnostic.

Comparator models must be trained only from the same frozen Stage 3G discovery data and must use the exact Stage 3G definitions and parameters.

`btc_return_60s` must remain separately visible in shadow logs and reports because it was a strong historical diagnostic in Stages 3F and 3G.

## Critical prospective-timing distinction

Milestone 4A distinguishes two different score types.

### 1. Prospective score — advancement eligible

A **prospective score** is created and durably appended **before** the source timestamp of a later target-account pair-completing execution.

Only prospective scores may enter the Milestone 4A advancement gate.

The score must be based solely on information already received by the engine at score creation time. Late-arriving prior fills that were not yet observed may not be retroactively inserted into that score.

### 2. Event-conditioned reconstruction score — diagnostic only

When polling or another source reveals a target-account fill after that fill has already happened, the engine may reconstruct the Stage 3G feature vector immediately before applying that fill and score it for online/offline parity diagnostics.

That score is **not prospective**, because the engine learned of the target event before producing the score. It must be marked `event_conditioned_reconstruction=true` and is permanently excluded from advancement metrics.

This distinction prevents a live system from claiming prospective prediction merely because the feature vector itself excludes the target fill.

## Prospective scoring trigger

The initial advancement-eligible shadow stream uses a **1 Hz scoring cadence** during active eligible BTC 5-minute markets in the frozen 12:00–18:00 UTC evaluation window.

Additionally, after the engine applies a newly observed prior target-account fill, it may produce an immediate event-driven score if all required inputs pass freshness checks. These event-driven scores are advancement eligible only if their durable creation time is strictly earlier than the later pair-completing target execution's source timestamp under the binding rule below.

A score is emitted only when:

- the market is an eligible BTC 5-minute binary market;
- market start can be derived using the same Stage 3G semantics;
- `0 <= elapsed_seconds < 300`;
- the state machine is initialized and not in an ambiguity quarantine;
- BTC causal reference requirements are satisfied;
- no critical input is marked stale under the frozen stale-data policy.

Every attempted cadence tick must produce either a score record or an explicit unscorable record with a reason code.

## Prospective score timestamp semantics

Each score record must contain:

- `score_id`;
- `run_id`;
- market/condition ID;
- asset/token mapping used for UP/DOWN;
- local UTC wall-clock score timestamp with millisecond or finer precision;
- monotonic-clock timestamp or elapsed monotonic value for latency measurement;
- feature `event_epoch` used to construct time/BTC features;
- maximum source timestamp among incorporated target-account fills;
- maximum deterministic fill-order key among incorporated fills;
- BTC reference close timestamp;
- per-source receive timestamps;
- feature schema version;
- model artifact fingerprints;
- model outputs;
- input freshness flags;
- write/commit completion timestamp.

A prediction is considered durably recorded only after the append-only sink confirms the record write.

## Prospective outcome binding

When an eligible target-account fill later completes one or more FIFO complementary pair events, the engine creates the normal Stage 3G labels:

- `pair_cost`;
- `favorable = pair_cost < 1.0`;
- `paired_shares`;
- `lag_seconds_label_only`.

For each resulting pair event, bind the **latest advancement-eligible score for that market whose durable score timestamp is strictly earlier than the beginning of the target fill's reported source second**:

`score_durable_epoch_ms < target_fill_timestamp_seconds * 1000`

This conservative rule is required because the public account-trade source exposes target timestamps at second resolution. A score created during the same reported source second is not allowed to prove that it preceded the target execution and therefore cannot enter the advancement gate.

If no such score exists, the pair event is recorded as `unbound_no_strictly_prior_score` and remains part of coverage diagnostics but not model-performance metrics.

If multiple FIFO pair rows are created by the same completing fill, the same latest strictly prior score may bind to each row, while each row retains its own `target_event_index`, `paired_shares`, `pair_cost`, and favorable label.

No later score may be substituted after the outcome is known.

## Account-trade ingestion

The initial implementation may use the official public Polymarket Data API `/trades` endpoint for the observed public wallet, explicitly requesting `takerOnly=false` so maker and taker fills are included.

The collector must:

- poll at a frozen default cadence of **1 request per second** during active evaluation windows;
- deduplicate idempotently using the repository's canonical source-trade identity rules;
- persist exact raw response bytes before normalization when practical, or an equivalently replayable canonical raw record plus response hash;
- record request start, response receive, parse, normalize, and state-apply timestamps;
- retain HTTP status, retry count, and request parameters;
- overlap polling windows/pages sufficiently to tolerate delayed appearance and reordered responses;
- never assume a response is complete merely because no new rows appeared in one poll;
- never mutate an already emitted prospective score when a late fill arrives.

If the public source returns records whose deterministic ordering cannot be resolved using the existing `(timestamp, source_trade_id)` canonical ordering, the affected interval must be quarantined and recorded rather than silently guessed.

The authenticated Polymarket user WebSocket is not part of the initial target-account path because it reports activity for the credential owner rather than serving as an arbitrary-public-wallet stream.

## Polymarket public market-data stream

The public Polymarket market WebSocket may be used for live market metadata, orderbook/price diagnostics, token subscriptions, and health telemetry.

It must not be used to infer that a public market trade belongs to the observed target account unless an independently reliable identity link exists.

Market-data fields are **not** part of the frozen Stage 3G primary feature vector. They may be recorded for future execution-feasibility work but must not enter Milestone 4A model inputs or the primary advancement gate.

## BTC reference ingestion

The historical Stage 3G BTC semantics are based on Coinbase BTC-USD **60-second candles**, where a candle is causal only after its close timestamp.

The initial live implementation may use either:

1. Coinbase Exchange public WebSocket trade/ticker data aggregated into deterministic 60-second OHLC candles; or
2. Coinbase Exchange public 60-second REST candles after the candle is closed.

Regardless of transport, the resulting `BtcCandle` semantics must match the existing Stage 3G representation:

- `open_epoch` aligned to the 60-second bucket start;
- `interval_seconds=60`;
- open/high/low/close values preserved with decimal-safe parsing;
- `close_epoch = open_epoch + 60`;
- a candle is unavailable to a score if `close_epoch > score event_epoch`.

The initial model must continue to use only the five Stage 3G BTC fields listed in the frozen primary feature set. Historical unsupported 15s/30s returns and realized-volatility fields remain excluded from model input.

## Frozen stale-data policy

A prospective score is unscorable if any of the following holds:

- no causal BTC candle exists at or before the score event epoch;
- the latest causal BTC candle close is more than **120 seconds** older than the score event epoch;
- the target-account collector has been continuously failing or disconnected for more than **5 seconds**;
- the engine is replaying/reconciling an unresolved ordering ambiguity;
- the active market/token mapping is unknown or internally inconsistent;
- the state machine has detected a non-idempotent duplicate or impossible inventory transition.

The exact reason must be logged.

A stale or missing value may not be silently forward-filled beyond the semantics already defined by Stage 3G.

## Online state machine

The online account state machine must preserve the Stage 3G pre-event semantics exactly for all previously observed fills.

For each eligible market, maintain at minimum:

- FIFO UP lots and DOWN lots;
- UP and DOWN cumulative inventory;
- paired inventory;
- residual inventory;
- inventory imbalance;
- last prior UP and DOWN fill timestamps;
- trailing prior-fill deque sufficient for 15s/30s/60s counts and quantities;
- trailing side-switch state;
- cumulative paired quantity;
- same-source-second prior-fill count;
- deterministic fill ordering metadata.

The target fill that completes a pair must never mutate an event-conditioned reconstruction snapshot before that snapshot is produced.

Late-arriving prior fills do not rewrite already durable prospective predictions. Instead, reconciliation records the divergence between arrival-time online state and fully reconstructed event-time state.

## Deterministic ordering

Historical Stage 3G uses `(timestamp, fill_sequence_number)` after canonical ledger construction, where canonical fills are sorted by `(timestamp, source_trade_id)`.

Milestone 4A must preserve an equivalent deterministic order for replay:

1. source timestamp ascending;
2. canonical source trade ID ascending for same-source-timestamp records;
3. stable local ingestion identifier only as a final replay tie-breaker and never as evidence that one same-second source event truly preceded another in the external system.

Same-second ambiguity must remain visible in provenance.

## Append-only persistence

The engine must use append-only durable records for:

- raw source observations;
- normalized target-account fills;
- BTC candles;
- market metadata changes;
- score attempts;
- successful predictions;
- unscorable ticks;
- outcome labels;
- score-to-outcome bindings;
- reconnects/retries/errors;
- state reconciliation events;
- replay/audit results.

A correction must be represented as a new record referring to the prior record; it must not overwrite the original observation or prediction.

Each record must include a schema version and `run_id`.

## Replay requirement

Given persisted source observations and a frozen model artifact, offline replay must reproduce:

- target-account normalized fill ordering;
- online state before each score;
- all primary feature values;
- model predictions within deterministic numeric tolerance;
- all unscorable decisions;
- FIFO outcomes;
- score-to-outcome bindings.

Replay must be possible without consulting live external APIs.

## Online/offline parity audit

Milestone 4A must report two parity classes separately:

### Arrival-time parity

Replaying the exact observations in their original receive order must reproduce the exact live scores and state transitions.

Required result: **100% deterministic reproduction** for advancement-eligible records, excluding only records explicitly marked corrupt/unreadable.

### Event-time reconstruction parity

After the observation horizon, all target-account fills may be sorted under the canonical historical rules and reconstructed using the Stage 3G materializer.

Compare each event-conditioned diagnostic snapshot and each eligible prospective outcome against this fully reconciled state. Differences caused by late data are expected operational observations and must be measured, not hidden.

## Frozen evaluation horizon

The prospective evaluation starts only after:

- this specification is committed;
- frozen model artifacts and fingerprints exist;
- deterministic unit/replay tests pass;
- a bounded non-live fixture/replay run passes;
- the operator starts a new `run_id` designated as `frozen_evaluation=true`.

No observation recorded before that run start may enter the advancement gate.

The primary evaluation continues until all of the following minimums are reached:

- at least **14 consecutive UTC calendar days** have elapsed from the first full evaluation day;
- at least **10 reportable evaluation days** exist;
- at least **20,000 prospectively bound pair-event rows** exist.

If the minimums are not met after 14 days, observation continues without model/spec changes until they are met or until **28 consecutive UTC calendar days** have elapsed. If the minimums are still not met at day 28, Milestone 4A is **INCONCLUSIVE**, not PASS.

A reportable evaluation day must contain at least **500 prospectively bound pair-event rows** in the frozen 12:00–18:00 UTC window.

## Frozen evaluation metrics

Metrics use the exact Stage 3G definitions and `paired_shares` weighting.

For each frozen model, report by UTC evaluation day and in aggregate:

- weighted MAE for `pair_cost`;
- unweighted MAE;
- weighted bias;
- Brier score for `favorable`;
- log loss;
- prediction count;
- total `paired_shares` weight.

Also report:

- target favorable prevalence;
- pair-cost distribution;
- prediction dispersion;
- calibration/reliability bins;
- performance by elapsed-time bucket;
- performance by inventory-imbalance bucket;
- performance by `btc_return_60s` bucket;
- prospective lead time from durable score to target source second;
- unbound eligible outcomes;
- stale/unscorable score attempts;
- data-arrival latency distributions;
- scoring latency distributions;
- reconnect/retry counts;
- event-time state divergence caused by late data.

## Frozen advancement gate

The primary candidate is `hgb_all_pre_event`.

Milestone 4A passes only if **all** of the following hold on the frozen prospective evaluation set:

1. aggregate weighted MAE is lower than `hgb_timing_inventory`;
2. aggregate Brier is lower than `hgb_timing_inventory`;
3. aggregate weighted MAE is lower than `linear_timing_inventory`;
4. aggregate Brier is lower than `linear_timing_inventory`;
5. `hgb_all_pre_event` beats `hgb_timing_inventory` on weighted MAE on at least **60% of reportable evaluation days**;
6. `hgb_all_pre_event` beats `hgb_timing_inventory` on Brier on at least **60% of reportable evaluation days**;
7. **100%** of advancement-eligible score/outcome bindings satisfy the strictly-prior durable timestamp rule;
8. arrival-time replay reproduces **100%** of advancement-eligible feature vectors, predictions, and bindings within deterministic numeric tolerance;
9. at least **90%** of otherwise eligible FIFO pair-event rows in reportable windows are bound to a strictly prior prospective score; unbound events must be explicitly accounted for;
10. the frozen model/feature/preprocessing fingerprints remain unchanged for the entire evaluation set;
11. every metric row in the advancement set can be traced to immutable source/provenance records and a specific frozen model artifact;
12. no order creation, signing, submission, cancellation, relayer transaction, or capital exposure occurred in the Milestone 4A process.

Do not weaken, reinterpret, or replace this gate after prospective results are observed.

## Failure and restart rules

The evaluation window must restart from a new `run_id` if any of the following occurs:

- primary model artifact changes;
- feature definitions/order change;
- score cadence or strict binding rule changes;
- stale-data thresholds change;
- target account changes;
- evaluation clock-time domain changes;
- a defect is discovered that could have changed any advancement-eligible prediction or inclusion decision;
- persistence loss prevents deterministic replay of advancement-eligible rows.

A restart is not required for a software change proven to be operationally irrelevant to all advancement-eligible outputs, but the proof and commit must be documented.

External API outages do not automatically restart the run. They produce missing/unscorable intervals and may cause a day to become non-reportable.

## Shadow-only safety boundary

Milestone 4A runtime code must not require a private trading key.

The initial implementation must not contain a code path used by the shadow runner that can:

- create an order;
- sign an order;
- submit an order;
- cancel an order;
- approve spending;
- transfer funds;
- call a relayer transaction endpoint.

Read-only API credentials, if ever required for a data source, must be isolated from future execution credentials and documented explicitly.

Tests must assert that the configured shadow engine exposes no execution action.

## Operational telemetry

Record at minimum:

- target-account poll request latency;
- target fill source-to-receive latency;
- BTC source-to-receive latency;
- score computation latency;
- score durable-write latency;
- end-to-end cadence drift;
- HTTP/WebSocket reconnects;
- retry/backoff events;
- duplicate records;
- late-arriving records;
- ordering quarantines;
- stale BTC intervals;
- stale account-source intervals;
- dropped/unscorable score ticks;
- persistence errors.

Latency metrics are required evidence but, in Milestone 4A, are not a claim about executable trading latency.

## Required tests before live observation

Tests must demonstrate at minimum:

1. exact primary feature order matches Stage 3G;
2. exact HGB parameters match Stage 3G;
3. target fill cannot mutate its own event-conditioned snapshot;
4. prospective scores never incorporate a source event received after score creation;
5. same-timestamp canonical ordering is deterministic;
6. rolling windows exclude unavailable/later fills;
7. BTC candles after score event time are unavailable;
8. BTC 60-second aggregation matches stored historical candle semantics on fixtures;
9. duplicate target-account API records are idempotent;
10. late target-account fills do not mutate prior durable scores;
11. strict score-to-outcome binding rejects same-source-second and later scores;
12. append-only records replay deterministically;
13. model artifact fingerprints are checked before scoring;
14. live outcomes cannot trigger fitting or calibration;
15. out-of-window observations cannot enter advancement metrics;
16. stale-data rules produce explicit unscorable records;
17. shadow runtime has no order/execution action;
18. bounded historical replay produces feature parity with the Stage 3G materializer for equivalent event-conditioned snapshots.

## Required artifacts

Milestone 4A must produce machine-readable and human-readable evidence including:

- frozen model manifest and artifact hashes;
- feature schema manifest;
- run manifest;
- raw/provenance observation log;
- normalized target-account fill log;
- BTC candle log;
- append-only prediction log;
- unscorable-attempt log;
- outcome and binding log;
- replay audit;
- event-time reconciliation audit;
- data-quality and latency report;
- per-day prospective metrics;
- aggregate prospective metrics;
- calibration report;
- advancement-gate booleans and overall PASS/FAIL/INCONCLUSIVE result;
- source repository commit provenance.

## Current API assumptions frozen for implementation planning

These assumptions were verified against official provider documentation on 2026-08-15 and must be rechecked at implementation time if an API behaves differently:

- Polymarket public Data API trade history: `GET https://data-api.polymarket.com/trades`, with public-wallet filtering and documented `limit`/`offset`; the repository already uses `user`, `takerOnly=false`, and optional bounded time parameters.
- Polymarket public market WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/market`, no authentication required for market subscriptions.
- Polymarket authenticated user WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/user`, requiring API credentials and intended for the authenticated user's own order/trade activity.
- Polymarket Data API `/trades` documented rate limit: 200 requests per 10 seconds, making the frozen 1 Hz target-account polling cadence conservative.
- Coinbase Exchange public WebSocket market feed: `wss://ws-feed.exchange.coinbase.com`.
- Coinbase Exchange REST BTC-USD candles support 60-second granularity.

If any assumption is false in live verification, the implementation must preserve the scientific contract above rather than silently substituting weaker timing/provenance semantics.

## Implementation sequence after freeze

1. add frozen model-artifact training/export and manifest validation;
2. define versioned event/record contracts and append-only local storage;
3. implement target-account polling adapter with receive-time provenance and idempotent deduplication;
4. implement Coinbase 60-second live reference adapter and parity tests;
5. implement market discovery/subscription needed to identify active eligible BTC 5-minute markets;
6. refactor/reuse Stage 3G state semantics behind an online state-machine interface;
7. implement 1 Hz prospective scoring plus event-driven post-prior-fill scores;
8. implement diagnostic event-conditioned reconstruction scoring;
9. implement strict prospective outcome binding;
10. implement deterministic replay and event-time reconciliation;
11. implement telemetry and machine-readable reports;
12. run deterministic tests and bounded historical replay;
13. only then start a new frozen prospective `run_id`.

## Deferred work

The following are explicitly outside Milestone 4A:

- orderbook-derived model features;
- spread/queue/fill-probability modeling;
- execution simulation used to claim profit;
- fees/slippage-adjusted profitability claims;
- neural-network challengers;
- model retuning from live data;
- order construction or submission;
- capital/risk management.

These may be considered only under separately frozen milestones after Milestone 4A evidence is evaluated.

## Source of truth and conflict rule

The Stage 3G causal semantics remain authoritative for feature definitions and historical parity, especially:

- `docs/MILESTONE_3G_PRE_EVENT_PREDICTION_SPEC.md`;
- `src/polymarket_edge_lab/analysis/stage3g_pre_event.py`;
- `src/polymarket_edge_lab/analysis/stage3g_models.py`;
- `src/polymarket_edge_lab/analysis/stage3e_models.py`;
- `src/polymarket_edge_lab/analysis/btc_features.py`;
- canonical ledger construction in `src/polymarket_edge_lab/reconstruction/ledger.py`.

This Milestone 4A specification is authoritative for prospective timing, live data arrival, score durability, binding, observation horizon, and advancement rules.

If executable code conflicts with either frozen specification, stop and investigate the discrepancy rather than selecting the more convenient interpretation.
