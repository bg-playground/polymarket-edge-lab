# Copilot / Codex Agent Prompt — Milestone 2

Use this prompt on branch `milestone-2-forensic-reconstruction-spec` after reviewing the updated `AGENTS.md` and `docs/MILESTONE_2_SPEC.md`.

---

@copilot Implement **Milestone 2: live-data validation and forensic reconstruction** for Polymarket Edge Lab.

Before changing code:

1. Read `AGENTS.md`.
2. Read `docs/MILESTONE_2_SPEC.md`.
3. Read `docs/RESEARCH_PLAN.md`.
4. Inspect the merged Milestone 1 implementation on this branch.
5. Preserve Milestone 1 architecture unless a concrete bug requires a targeted fix.
6. Do not implement anything prohibited by `AGENTS.md`.

## Objective

Turn the Milestone 1 collection pipeline into a defensible forensic reconstruction pipeline for target trader `nagi777`.

The milestone must live-validate current Polymarket Data API behavior, acquire maker-inclusive history, reconstruct per-market UP/DOWN inventory chronologically, calculate paired versus directional exposure, calculate defensible paired-set acquisition cost, and generate claim-validation reports for the public statistics we are investigating.

## Required implementation sequence

### Phase A — Live API validation first

Before building downstream assumptions, add an explicitly invoked live-validation command/test that observes a real public Data API response.

Verify and document:

- actual response field names/types;
- observed `timestamp` unit;
- behavior of `takerOnly=false`;
- behavior of `start` and `end` filters;
- response ordering;
- maximum practical page `limit`;
- offset 10,000 behavior;
- whether `id` is present/unique;
- any relevant undocumented public fields.

Write findings to `docs/LIVE_API_VALIDATION.md` with verification date and clear separation between observed facts and remaining assumptions.

If live network access is unavailable to the coding agent, do **not** fabricate verification. Implement the validation command and mark the milestone blocked on live verification until it is run in an environment with network access.

### Phase B — Configure the target

Add a small configuration mechanism for research targets.

Configure:

```text
nickname: nagi777
proxy_wallet: verified public 0x address
verification metadata
```

Do not bury the address in collector code.

### Phase C — Small maker-inclusive collection

Run or provide an exact command for a small real sample using:

```text
takerOnly=false
```

and verify that raw preservation, normalization, DuckDB/Parquet persistence, and validation still work with the live shape.

### Phase D — Canonical ledger

Implement a deterministic canonical chronological ledger per market.

Preserve at minimum:

```text
source_trade_id
account
market_id
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
source provenance
```

Do not classify ambiguous markets as UP/DOWN.

### Phase E — Market eligibility

Add conservative binary-market eligibility classification.

Every observed market should be either:

```text
eligible_binary_market = true
```

or excluded with a recorded reason.

Incomplete-history markets must not contribute to aggregate pair-edge claims.

### Phase F — Inventory reconstruction

Replay fills in chronological order per market.

Support BUY and SELL events explicitly.

At every event calculate appropriately defined:

```text
UP inventory
DOWN inventory
paired inventory
directional residual side
directional residual quantity
```

Do not assume all fills are buys.

### Phase G — Pair accounting

Implement two documented methods:

1. **Primary: weighted-average inventory accounting**
2. **Secondary sensitivity: FIFO lot pairing**

Calculate:

```text
pair_cost
gross_pair_edge = 1 - pair_cost
```

Use `Decimal` throughout accounting.

Do not use future fills to improve the primary pair cost. Do not optimize matching and call it realized performance.

### Phase H — Exposure metrics

Calculate paired versus directional exposure under multiple clearly labeled definitions, including at least:

- event/share weighted;
- end-of-market;
- dollar-cost weighted where defensible.

Do not select a definition because it happens to reproduce 78.7% / 21.3%.

### Phase I — Claim-validation report

Generate both JSON and Markdown reports for `nagi777`.

Test at least these public claims:

```text
51.25 trades / active hour
$110.67 average trade
50% win rate (mark inconclusive unless metric can be defined)
98.43¢ average pair cost
1.57¢ gross paired edge
78.7% paired inventory
21.3% directional residual
+$126,836 total P&L (only if genuinely measurable from available data)
```

Each claim must include:

```text
measured value
methodology
sample size
completeness caveats
status: supported / not supported / inconclusive
```

Do not invent P&L or settlement data if Milestone 2 does not yet contain enough information to measure it.

## Deep-history requirements

Use maker-inclusive, windowed collection.

Prefer automatic subdivision of any window that reaches the offset ceiling. If not implemented, the pipeline must visibly fail the completeness gate and identify the exact window requiring a smaller interval.

A market/history must never be labeled complete when unresolved ceiling hits or source gaps remain.

## Suggested modules

```text
src/polymarket_edge_lab/
  reconstruction/
    ledger.py
    inventory.py
    pairing.py
    exposure.py
    market_summary.py

  analysis/
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

You may adapt this structure if the existing package architecture suggests a cleaner separation, but explain meaningful deviations.

## Required deterministic tests

Add hand-calculated regression tests for at least:

- seconds timestamp path;
- milliseconds compatibility path if retained;
- `takerOnly=false` requests;
- `start` / `end` requests;
- offset 10,000 behavior;
- window exhaustion and incomplete-window detection;
- subdivision if implemented;
- cross-window duplicates;
- chronological sorting;
- basic UP/DOWN buys;
- SELL reducing inventory;
- partial pairing;
- weighted-average pair cost;
- FIFO pair cost;
- gross edge math;
- directional residual calculations;
- incomplete market exclusion;
- deterministic report generation.

Use the hand-calculated example from `docs/MILESTONE_2_SPEC.md` as one regression fixture.

## Important restrictions

Do not implement:

- live trading;
- wallet/private-key functionality;
- order placement;
- strategy cloning;
- BTC prediction models;
- ML;
- neural networks;
- LangGraph;
- LLM calls;
- strategy backtesting;
- optimization intended to maximize apparent historical P&L.

This milestone is forensic measurement only.

## CI and quality gate

Before declaring completion, all of these must pass in GitHub Actions:

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

## Deliverables

At completion, provide a PR summary containing:

1. live API facts verified;
2. target wallet verification method;
3. modules/files added;
4. exact accounting definitions;
5. test count and CI status;
6. data-quality limitations;
7. exact command for a small real `nagi777` run;
8. exact command for the full historical forensic run;
9. sample report paths;
10. any claims that cannot yet be measured and why.

Do not proceed to Milestone 3.