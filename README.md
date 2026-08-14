# Polymarket Edge Lab

Forensic reconstruction, market-microstructure research, and systematic edge discovery for short-duration prediction markets.

## Current phase

**Milestone 2: live validation and forensic reconstruction.**

The immediate goal is to live-validate public API behavior and reconstruct a trustworthy, reproducible `nagi777` trade/inventory ledger for claim validation (paired inventory, directional residuals, pair cost, trading frequency, and measurable economics).

This repository is intentionally **not** starting with live trading, wallet signing, LangGraph, neural networks, or strategy optimization.

## Architecture

```
src/polymarket_edge_lab/
  collectors/polymarket.py   # HTTP transport: fetches raw pages from Data API
  normalization/trades.py    # Converts raw dicts → NormalizedTrade objects
  storage/raw.py             # Atomic create-only raw-byte storage + manifest
  storage/normalized.py      # Parquet and DuckDB write/read (no pandas required)
  validation/report.py       # ValidationReport dataclass + build_report()
  models/trade.py            # NormalizedTrade Pydantic model

scripts/
  collect_historical_trades.py   # CLI orchestrator
  validate_live_api.py           # Explicit live Data API validation gate
  reconstruct_trader.py          # Canonical ledger + inventory + market summaries
  generate_claim_report.py       # JSON/Markdown claim validation outputs

tests/
  fixtures/                      # Small deterministic JSON fixtures
  unit/                          # Deterministic unit tests (no network)
  integration/                   # Opt-in live API tests
```

### Module responsibilities

| Module | Responsibility |
|---|---|
| `collectors/polymarket.py` | HTTP transport only. Fetches raw bytes + parsed JSON. No normalization. |
| `normalization/trades.py` | Field mapping, Decimal parsing, UTC conversion, identity hash, rejection. |
| `storage/raw.py` | Immutable raw-byte storage (atomic writes), content hash, JSONL manifest. |
| `storage/normalized.py` | Parquet + DuckDB write/read with upsert-style duplicate detection. |
| `validation/report.py` | Validation summary counts and earliest/latest timestamps. |
| `models/trade.py` | `NormalizedTrade` Pydantic model (frozen, UTC-aware timestamps, Decimal). |

## Live API validation gate

Run this command before relying on API assumptions:

```bash
python scripts/validate_live_api.py --account 0xVERIFIED_PUBLIC_PROXY_WALLET
```

It writes `docs/LIVE_API_VALIDATION.md` with:
- observed facts from live responses;
- unresolved assumptions;
- a visible **BLOCKED** status when network access or verified target metadata is unavailable.

## Endpoint and response assumptions (until live gate succeeds)

**Endpoint:** `GET https://data-api.polymarket.com/trades`  
**Parameters:** `user` (proxy wallet address), `offset` (int), `limit` (int)  
**Response:** JSON array of trade objects  
**Verification date:** 2026-08-14 (from official Polymarket docs; live response shape
could not be confirmed during agent execution due to network restrictions — see
`tests/fixtures/README.md` for documented field assumptions)

Key confirmed fields:
- `id` — trade identifier (used as `source_trade_id` when present)
- `market` — condition ID (hex string)
- `asset_id` — token/share ID
- `side` — `"BUY"` or `"SELL"`
- `size` — share quantity (string-encoded decimal)
- `price` — price per share (string, 0–1 range)
- `match_time` — Unix seconds (string-encoded integer)
- `outcome` — outcome label (preserved as-is; e.g. `"UP"`, `"DOWN"`)
- `owner` — proxy wallet address
- `transaction_hash` — on-chain tx hash (may be absent)

## Raw immutability / provenance

Raw pages are written as **exact response bytes** (not re-serialized JSON).
Each file is written atomically (temp file + rename) and never overwritten.
A sidecar `<account>_manifest.jsonl` records:
- `offset`, `limit`, `filename`, `content_hash` (SHA-256), `collected_at`, `endpoint_url`, `record_count`

Normalized records retain `_raw_page_path`, `_raw_page_hash`, `_page_offset`,
and `_record_index` in `raw_extra` for provenance tracing.

## Resumability and deduplication semantics

- On re-run, offsets already in the manifest are skipped (use `--force` to override).
- DuckDB uses `PRIMARY KEY (source_trade_id)` — duplicate inserts are skipped, not errored.
- `source_trade_id` = API `id` when present; otherwise a deterministic SHA-256 of
  `(transaction_hash, asset_id, side, price, size, match_time, owner)`.
- **Known limitation:** Economically identical fills in one transaction may be
  indistinguishable if the API omits a fill `id`.

## API offset / history limitation

The Data API has a **documented offset ceiling of 10 000**. Records beyond
this bound may not be accessible via this public endpoint. The collector
detects this boundary and reports it clearly rather than claiming full history.

## Non-goals for Milestone 1

Do not implement:

- live order placement;
- wallet/private-key handling;
- automated trading;
- maker/taker optimization;
- LangGraph or multi-agent orchestration;
- machine learning;
- neural networks;
- strategy backtesting;
- P&L optimization.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Quality checks

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

## Running tests

```bash
# Unit tests (deterministic, no network):
pytest tests/unit/

# All tests including integration (requires network + account):
POLYMARKET_INTEGRATION_TESTS=1 POLYMARKET_TEST_ACCOUNT=0xYOUR_ADDR pytest
```

## Sample end-to-end run (mocked / dry-run)

```bash
python scripts/collect_historical_trades.py \
    --account 0x0000000000000000000000000000000000000001 \
    --max-pages 1 \
    --dry-run
```

## Target configuration (`nagi777`)

Research targets are configured in:

`config/targets.json`

`nagi777` metadata includes:
- `nickname`
- `proxy_wallet` (must be verified from public evidence; never guessed)
- `verification_source`
- `verification_date_utc`
- `verification_status`

## Small real `nagi777` sample collection

1. Verify `nagi777` proxy wallet from public evidence (e.g. profile page).
2. Run:

```bash
python scripts/collect_historical_trades.py \
    --account 0xVERIFIED_NAGI777_PROXY \
    --windowed \
    --global-start 1735689600 \
    --global-end 1735776000 \
    --window-seconds 3600 \
    --min-window-seconds 900 \
    --page-size 100 \
    --raw-dir data/raw \
    --normalized-dir data/normalized \
    --duckdb-path data/polymarket_edge_lab.duckdb
```

## Full historical `nagi777` forensic collection

```bash
python scripts/collect_historical_trades.py \
    --account 0xVERIFIED_NAGI777_PROXY \
    --windowed \
    --global-start 1569888000 \
    --window-seconds 2592000 \
    --min-window-seconds 3600 \
    --page-size 500 \
    --raw-dir data/raw \
    --normalized-dir data/normalized \
    --duckdb-path data/polymarket_edge_lab.duckdb
```

If unresolved windows remain after subdivision, completeness is reported visibly and the command exits non-zero.

## Reconstruction and claim validation

```bash
python scripts/reconstruct_trader.py \
    --target nagi777 \
    --account 0xVERIFIED_NAGI777_PROXY \
    --duckdb-path data/polymarket_edge_lab.duckdb \
    --output-dir reports \
    --history-complete

python scripts/generate_claim_report.py \
    --target nagi777 \
    --account 0xVERIFIED_NAGI777_PROXY \
    --duckdb-path data/polymarket_edge_lab.duckdb \
    --output-dir reports \
    --history-complete
```

Report paths:
- `reports/nagi777_claim_validation.json`
- `reports/nagi777_claim_validation.md`

Accounting conventions:
- Primary pair-cost method: weighted-average inventory accounting at pair-increase events.
- Portfolio-level pair-cost claim metric: pair-quantity-weighted mean over complete eligible markets.
- Secondary sensitivity: FIFO cost of final paired inventory.
- Pair-formation flow is reported separately as gross positive paired-inventory deltas; ending paired inventory is reported independently.
- Gross pair edge: `1 - pair_cost`.
- Exposure metrics: event/share-weighted, end-of-market, and dollar-cost-weighted.

## Known limitations

- **No live API confirmation during development:** Network access was unavailable
  during agent implementation. Run `scripts/validate_live_api.py` in a network-enabled
  environment before marking live validation complete.
- **Offset ceiling:** The Data API appears to limit responses to offset ≤ 10 000.
  Complete trade history may not be available for accounts with > 10 000 trades.
- **No unique fill ID guarantee:** If the API returns multiple economically identical
  fills in one transaction without a fill `id`, they may hash to the same
  `source_trade_id` and be treated as duplicates.
- **nagi777 proxy wallet:** must be verified from public evidence and stored in
  `config/targets.json`; never hard-code or guess.

## Data policy

Raw source data belongs under `data/raw/` and should never be edited in place.
Normalized derived data belongs under `data/normalized/`.

Large datasets are intentionally ignored by Git. Commit schemas, fixtures,
validation reports, and small test samples — not complete production datasets.

## Development philosophy

- Measure before modeling.
- Preserve source truth.
- Make every transformation reproducible.
- Prefer deterministic code for accounting and validation.
- Treat surprising data as a bug until independently explained.
- Keep research assumptions explicit and testable.

See [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) for the longer-term research blueprint.
