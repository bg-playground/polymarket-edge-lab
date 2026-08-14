# Polymarket Edge Lab

Forensic reconstruction, market-microstructure research, and systematic edge discovery for short-duration prediction markets.

## Current phase

**Milestone 1 only: historical data acquisition and validation.**

The immediate goal is to build a trustworthy, reproducible historical trade ledger that can later be used to reconstruct `nagi777`'s inventory and test claims about paired inventory, directional residuals, pair cost, trading frequency, and P&L.

This repository is intentionally **not** starting with live trading, wallet signing, LangGraph, neural networks, or strategy optimization.

## Research sequence

1. Acquire public historical fills.
2. Preserve raw source data unchanged.
3. Normalize into typed internal models.
4. Validate and reconcile records.
5. Persist normalized data reproducibly.
6. Only after data quality is established, reconstruct inventory and test the published claims.

See [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) for the longer-term research blueprint.

## Milestone 1 acceptance criteria

Milestone 1 is complete only when the project can:

- retrieve a known sample of public trades for a configured account;
- save the original API payload unchanged;
- normalize supported records into typed models;
- persist normalized records locally;
- reload them without loss;
- detect malformed, duplicate, or inconsistent records;
- produce a concise validation report;
- pass unit tests and integration tests;
- run formatting/linting/type-checking/tests in CI.

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

## Suggested local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Data policy

Raw source data belongs under `data/raw/` and should never be edited in place. Normalized derived data belongs under `data/normalized/`.

Large datasets are intentionally ignored by Git. Commit schemas, fixtures, validation reports, and small test samples—not complete production datasets.

## Development philosophy

- Measure before modeling.
- Preserve source truth.
- Make every transformation reproducible.
- Prefer deterministic code for accounting and validation.
- Treat surprising data as a bug until independently explained.
- Keep research assumptions explicit and testable.
