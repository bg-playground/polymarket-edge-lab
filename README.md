# Polymarket Edge Lab

Forensic reconstruction, market-microstructure research, and systematic edge discovery for short-duration prediction markets.

## Current phase

**Milestone 1 only: historical data acquisition and validation.**

The immediate goal is to build a trustworthy, reproducible historical trade ledger that can later be used to reconstruct `nagi777`'s inventory and test claims about paired inventory, directional residuals, pair cost, trading frequency, and P&L.

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

## Verified endpoint and response assumptions

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

## First real `nagi777` collection run

1. Find the proxy wallet address for `nagi777`:
   - Visit https://polymarket.com/profile/nagi777
   - Copy the proxy wallet address (0x…) shown on the profile page.

2. Run the collector (replace `0xSEE_STEP_1` with the verified address):

```bash
python scripts/collect_historical_trades.py \
    --account 0xSEE_STEP_1 \
    --page-size 100 \
    --raw-dir data/raw \
    --normalized-dir data/normalized \
    --duckdb-path data/polymarket_edge_lab.duckdb
```

## Known limitations

- **No live API confirmation during development:** Network access was unavailable
  during agent implementation. Field mappings are based on official Polymarket docs.
  Run the integration test with a real account to verify response shape.
- **Offset ceiling:** The Data API appears to limit responses to offset ≤ 10 000.
  Complete trade history may not be available for accounts with > 10 000 trades.
- **No unique fill ID guarantee:** If the API returns multiple economically identical
  fills in one transaction without a fill `id`, they may hash to the same
  `source_trade_id` and be treated as duplicates.
- **nagi777 proxy wallet:** The proxy wallet address for `nagi777` must be obtained
  manually from the Polymarket UI before running the collector.

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
