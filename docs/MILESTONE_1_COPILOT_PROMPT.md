# Copilot Agent Prompt — Milestone 1

Use this prompt after the repository has been created and the bootstrap files are committed.

---

You are implementing **Milestone 1 only** of Polymarket Edge Lab.

Before changing code:

1. Read `AGENTS.md`.
2. Read `README.md`.
3. Read `docs/RESEARCH_PLAN.md`.
4. Inspect the current repository structure and tests.
5. Do not implement anything prohibited by `AGENTS.md`.

## Objective

Build a robust historical public-trade acquisition pipeline for the configured research account.

The pipeline must:

1. Confirm the current official Polymarket public trade-history endpoint and actual response shape before coding field mappings.
2. Fetch historical trades with pagination.
3. Preserve each raw API page unchanged under `data/raw/`.
4. Normalize supported trade records into typed `NormalizedTrade` objects.
5. Persist normalized data in Parquet and/or DuckDB.
6. Be resumable and avoid silently duplicating records.
7. Produce a validation summary covering:
   - total raw records;
   - normalized records;
   - rejected records;
   - duplicates;
   - missing required fields;
   - earliest/latest timestamps.
8. Add deterministic unit tests using small committed fixtures.
9. Add an integration test that can be explicitly enabled to query a small public sample.
10. Update the README with exact commands.

## Critical constraints

- Do not implement live trading.
- Do not add wallet signing or private keys.
- Do not add LangGraph.
- Do not add LLM calls.
- Do not add machine learning.
- Do not calculate or optimize a trading strategy.
- Do not invent undocumented API fields.
- Do not silently coerce ambiguous data.
- Keep raw data immutable.
- Use UTC internally.
- Use `Decimal` where price/size precision matters.
- Separate HTTP transport, normalization, storage, and validation into different modules.

## Preferred implementation style

Keep functions small and testable. Favor explicit dataclasses/Pydantic models over loosely typed dictionaries once data crosses the normalization boundary.

Suggested modules:

```text
collectors/polymarket.py
normalization/trades.py
storage/raw.py
storage/normalized.py
validation/trades.py
```

Add a CLI or script that supports a command resembling:

```bash
python scripts/collect_historical_trades.py --account <ACCOUNT>
```

The implementation must fail clearly when the public API changes instead of silently producing corrupted normalized data.

## Acceptance criteria

Do not declare the milestone complete until:

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

all pass and a documented end-to-end collection command can:

1. fetch a small sample;
2. write raw JSON;
3. normalize it;
4. persist it;
5. reload it;
6. print a validation report.

At the end, summarize:

- files changed;
- API assumptions verified;
- tests added;
- known limitations;
- exact command for the first real `nagi777` collection run.

Do not proceed to inventory reconstruction. That is Milestone 2.
