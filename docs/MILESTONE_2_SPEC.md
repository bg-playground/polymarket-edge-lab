# Milestone 2 — Live Validation and Forensic Reconstruction

## Purpose

Milestone 2 turns the Milestone 1 acquisition pipeline into a defensible forensic reconstruction system for `nagi777`.

The goal is **not** to infer or copy a trading strategy yet. The goal is to establish a trustworthy factual record of what the account did, how inventory evolved, and whether the public claims about paired inventory and complete-set economics are supported by the data.

---

## Primary Research Questions

Milestone 2 should answer:

1. What is the verified public proxy-wallet/account identity associated with `nagi777`?
2. Can the project retrieve the complete obtainable maker-inclusive public trade history for that account?
3. What is the live-observed Data API response shape and timestamp unit?
4. How many fills, markets, active hours, and dollars of notional are observable?
5. For each binary market, how did UP and DOWN inventory evolve chronologically?
6. What proportion of inventory/exposure was paired versus directional residual?
7. What was the acquisition cost of paired inventory under defensible accounting conventions?
8. Is the reported ~98.43¢ average paired-set cost reproducible?
9. Is the implied ~1.57¢ gross complete-set edge reproducible?
10. Is the reported ~78.7% paired / 21.3% directional composition reproducible?
11. Are the reported ~51.25 trades per active hour and ~$110.67 average trade reproducible?
12. What claims remain unsupported or inconclusive because public data cannot prove them?

---

## Scope Boundary

### Included

- live Data API verification;
- maker-inclusive historical collection;
- windowed deep-history collection;
- account/wallet verification;
- per-market chronological ledgers;
- inventory reconstruction;
- paired versus residual exposure;
- weighted-average and FIFO accounting;
- pair cost and gross edge;
- market-level realized economics where observable;
- claim-validation reports;
- data-quality and completeness reporting.

### Excluded

- strategy inference;
- BTC/ETH external-market feature alignment;
- machine learning;
- neural networks;
- LangGraph;
- autonomous research agents;
- backtesting a cloned strategy;
- live trading;
- wallet signing;
- order submission.

Those belong to later milestones.

---

# 1. Live API Verification Gate

Before building reconstruction logic on top of assumptions, run an explicitly enabled live validation against a real public account.

Capture and document:

- exact endpoint;
- query parameters sent;
- whether `takerOnly=false` returns maker-inclusive history as expected;
- observed `timestamp` magnitude and unit;
- observed field names and types;
- whether `start` and `end` window filters behave as documented;
- ordering semantics;
- maximum practical `limit`;
- behavior at offset 10,000;
- whether any unique row/fill ID exists in the response;
- any undocumented fields useful for provenance.

Do not commit private credentials. Small sanitized fixtures derived from public responses are acceptable if they contain only public information and are appropriate for the repository.

The project should produce a document such as:

`docs/LIVE_API_VALIDATION.md`

with verification date, sample query, observed facts, remaining uncertainties, and links/references to official documentation.

---

# 2. Target Identity

The target trader should be configurable.

For `nagi777`, record:

```text
nickname: nagi777
proxy_wallet: <verified 0x address>
verification_source: <public source description>
verification_date: <UTC date>
```

Store this in configuration or a small research-target file rather than hard-coding the address into collector logic.

Example:

```yaml
targets:
  nagi777:
    proxy_wallet: "0x..."
    nickname: "nagi777"
    verified_at: "2026-08-14T...Z"
```

---

# 3. Historical Collection Completeness

Use the Milestone 1 collector with:

```text
takerOnly=false
start=<epoch seconds>
end=<epoch seconds>
offset=<page offset>
limit=<page size>
```

Collection must support high-volume history beyond the per-query offset ceiling.

## Requirements

- deterministic windows;
- window provenance in raw manifests;
- maker-inclusive requests;
- resume support;
- raw-byte preservation;
- no mutation of collected raw data;
- visible warnings for unresolved ceiling hits;
- deduplication with documented limitations;
- collection-completeness summary.

If a window reaches the offset ceiling, the system must not claim full history for that window.

Preferred behavior is to **automatically subdivide the window** until either:

1. pagination exhausts normally, or
2. a configured minimum window duration is reached and completeness remains unresolved.

If automatic subdivision is not implemented, the system must fail the completeness gate and provide exact windows that require re-collection with a smaller interval.

---

# 4. Canonical Trade Ledger

Create a canonical chronological ledger containing at minimum:

```text
source_trade_id
account
market_id / condition_id
asset_id
outcome
side
timestamp
price
shares
notional
transaction_hash
outcome_index
slug
event_slug
title
raw provenance
```

Derived fields may include:

```text
market_sequence_number
fill_sequence_number
is_binary_up_down
normalized_outcome_side
```

Do not classify ambiguous outcomes as UP/DOWN unless the market metadata clearly supports that interpretation.

---

# 5. Market Eligibility

Milestone 2 should reconstruct only markets that can be treated as binary complementary-outcome markets with adequate confidence.

For each market, classify:

```text
eligible_binary_market = true / false
reason
```

Examples of reasons for exclusion:

- incomplete metadata;
- more than two outcomes;
- ambiguous token mapping;
- unresolved history completeness;
- malformed records;
- missing settlement information where required.

Excluded markets should remain visible in the report rather than disappearing silently.

---

# 6. Chronological Inventory Engine

Replay fills in chronological order per market.

Maintain for each outcome:

```text
shares_bought
shares_sold
net_shares
buy_cost
sell_proceeds
weighted_average_buy_cost
```

For a two-outcome market:

```text
UP inventory
DOWN inventory
```

At each event calculate:

```text
paired_shares = min(net_up, net_down)
directional_up = max(net_up - net_down, 0)
directional_down = max(net_down - net_up, 0)
```

If sells or negative inventory complicate this model, the engine must explicitly define how matched inventory is released and test the accounting rules. Do not assume all fills are buys.

Produce an inventory-event table such as:

| timestamp | action | outcome | price | shares | UP inv | DOWN inv | paired | directional side | directional shares |
|---|---|---|---:|---:|---:|---:|---:|---|---:|

---

# 7. Pair-Cost Accounting

The primary pair-cost calculation must be defensible and non-cherry-picked.

## Primary method: weighted-average inventory accounting

At each point where paired inventory increases, calculate the effective weighted-average costs of the complementary inventory used to form the paired quantity.

Conceptually:

```text
pair_cost = effective_up_cost + effective_down_cost
gross_pair_edge = 1.00 - pair_cost
```

## Secondary sensitivity: FIFO

Also report FIFO lot pairing as a sensitivity analysis.

## Optional theoretical bound

An optimized pairing method may be added only if explicitly labeled:

`THEORETICAL OPTIMIZED MATCHING — NOT PRIMARY REALIZED ACCOUNTING`

Never use future fills to improve the primary historical pair-cost result.

---

# 8. Exposure Definitions

The original public claim says roughly 78.7% paired and 21.3% directional.

Because percentages can vary by definition, calculate several transparent measures:

### Share-event weighted

At each inventory event:

```text
paired_share_exposure
directional_share_exposure
```

### Dollar-cost weighted

Use attributable acquisition cost where defensible.

### End-of-market exposure

Measure paired and residual inventory immediately before settlement / final observable state.

### Time-weighted exposure

Optional if event timestamps permit reliable interval weighting.

Report all definitions rather than selecting whichever reproduces the X post most closely.

---

# 9. Market-Level Economics

For each eligible market produce a summary containing, where observable:

```text
market_id
asset pair / outcomes
first_trade_timestamp
last_trade_timestamp
fill_count
total_buy_notional
total_sell_notional
ending_up_shares
ending_down_shares
max_paired_shares
ending_paired_shares
ending_directional_side
ending_directional_shares
weighted_avg_up_cost
weighted_avg_down_cost
weighted_pair_cost
weighted_gross_pair_edge
FIFO_pair_cost
FIFO_gross_pair_edge
history_complete
validation_warnings
```

If settlement outcomes/payouts are reliably obtainable during this milestone, add realized P&L fields. If not, leave realized P&L for the next data-enrichment step rather than guessing.

---

# 10. Aggregate Claim Validation

Produce a machine-readable and Markdown report.

Suggested outputs:

```text
reports/nagi777_claim_validation.json
reports/nagi777_claim_validation.md
```

The report should include:

| Public claim | Measured result | Method | Sample size | Status |
|---|---:|---|---:|---|
| 51.25 trades/active hour | X | documented definition | N | supported / not supported / inconclusive |
| $110.67 average trade | X | mean absolute fill notional | N | ... |
| 50% win rate | X / undefined | define metric before measuring | N | ... |
| 98.43¢ pair cost | X | weighted-average primary | N paired units | ... |
| 1.57¢ gross edge | X | 1 - pair cost | N | ... |
| 78.7% paired | X | multiple definitions | N | ... |
| 21.3% directional | X | multiple definitions | N | ... |
| +$126,836 | X / not yet measurable | realized P&L methodology | N | ... |

Use tolerance bands only when justified. Prefer reporting the actual measurement and uncertainty rather than forcing pass/fail to an arbitrary exact number.

---

# 11. Win Rate Must Be Defined

Do not implement a generic `win_rate` until its meaning is explicit.

Possible definitions include:

- percentage of markets with positive realized P&L;
- directional residual side winning the market;
- percentage of individual fills that later moved favorably;
- percentage of directional predictions correct.

The X post's "50% win rate" is ambiguous. Mark it **inconclusive** unless the metric can be reconstructed from context or explicitly defined.

---

# 12. Data Quality Report

Produce a separate completeness/data-quality summary:

```text
raw pages fetched
windows attempted
windows complete
windows unresolved
raw records
normalized records
rejected records
duplicates detected
markets observed
markets eligible
markets excluded
minimum timestamp
maximum timestamp
maker-inclusive flag verified
live schema verified
```

No aggregate claim should be presented without its data-quality context.

---

# 13. Proposed Modules

Suggested structure:

```text
src/polymarket_edge_lab/
  reconstruction/
    __init__.py
    ledger.py
    inventory.py
    pairing.py
    exposure.py
    market_summary.py

  analysis/
    __init__.py
    claim_validation.py
    trading_activity.py

  validation/
    completeness.py

  models/
    reconstruction.py

scripts/
  validate_live_api.py
  reconstruct_trader.py
  generate_claim_report.py
```

Reuse existing collectors and storage modules where possible.

---

# 14. Tests

At minimum add tests for:

- seconds timestamp live-shape fixture;
- milliseconds timestamp compatibility/guard path if retained;
- `takerOnly=false` request construction;
- `start`/`end` request construction;
- offset 10,000 behavior;
- window exhaustion;
- unresolved ceiling behavior;
- window subdivision if implemented;
- duplicate handling across windows;
- chronological sorting;
- simple all-buy UP/DOWN inventory;
- sells reducing inventory;
- partial pairing;
- multiple-price weighted-average cost;
- FIFO pairing;
- pair-cost edge math;
- paired/residual exposure math;
- malformed/ambiguous binary markets;
- incomplete-history markets being excluded from aggregate pair-edge claims;
- deterministic report output.

Include regression cases with hand-calculated expected results.

---

# 15. Acceptance Example

A deterministic fixture like:

```text
BUY 100 UP   @ .44
BUY  50 UP   @ .42
BUY  80 DOWN @ .53
BUY  70 DOWN @ .51
```

should reconstruct:

```text
UP shares = 150
DOWN shares = 150
paired shares = 150
residual shares = 0

UP cost = 65.00
UP weighted avg = .433333...

DOWN cost = 78.10
DOWN weighted avg = .520666...

weighted pair cost = .954000...
gross pair edge = .046000...
```

Tests should use `Decimal` and clearly defined rounding only at presentation boundaries.

---

# 16. Milestone 2 Definition of Done

Milestone 2 is complete when:

1. Live API behavior has been observed and documented.
2. `nagi777` target identity is verified/configured.
3. A real public sample is successfully collected maker-inclusive.
4. The system can collect deep history using time windows without falsely claiming completeness.
5. The canonical ledger is generated.
6. Eligible binary markets are identified conservatively.
7. Chronological inventory reconstruction passes deterministic tests.
8. Weighted-average and FIFO pair-cost methods pass hand-calculated tests.
9. Paired and directional exposure statistics are generated under explicit definitions.
10. Aggregate trading-activity statistics are produced.
11. The public X claims are reported as supported, unsupported, or inconclusive with methodology and sample size.
12. CI is green.
13. No strategy inference, ML, LangGraph, or live trading has leaked into this milestone.

---

## Recommended First Execution Order

```text
1. Live API validation
        ↓
2. Verify/configure nagi777 wallet
        ↓
3. Small real-data collection
        ↓
4. Inspect data-quality report
        ↓
5. Build canonical ledger
        ↓
6. Implement inventory engine
        ↓
7. Implement pair accounting
        ↓
8. Generate per-market summaries
        ↓
9. Run full historical collection
        ↓
10. Generate aggregate claim-validation report
```

The full-history run should come **after** the reconstruction logic and live assumptions are validated on a small sample, so a bad schema or accounting assumption does not contaminate a large dataset.