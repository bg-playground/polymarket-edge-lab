# Agent Instructions

Read `docs/RESEARCH_PLAN.md` for the overall project direction.

## Current scope

Work on **Milestone 1: historical data acquisition, normalization, storage, and validation only**.

Do not move ahead to later milestones unless the repository owner explicitly changes this file.

## Required behavior

- Use official/current public Polymarket interfaces when implementing collectors.
- Confirm API response shapes against real responses before hard-coding assumptions.
- Preserve raw responses before transforming them.
- Use typed Python models for normalized records.
- Separate transport/API code from normalization and storage logic.
- Make collectors resumable and idempotent where practical.
- Detect duplicates explicitly.
- Use UTC internally for timestamps.
- Add tests for every parsing/normalization rule.
- Keep fixtures small and deterministic.
- Log data-quality issues rather than silently repairing ambiguous records.
- Prefer explicit failure over guessed field mappings.
- Keep secrets out of source control.
- Add or update documentation when behavior changes.

## Prohibited in the current phase

Do not implement:

- live trading;
- order submission;
- wallet signing;
- private-key storage;
- autonomous trading;
- LangGraph;
- LLM agents;
- neural networks;
- machine-learning strategy models;
- strategy optimization;
- simulated profitability claims.

## Engineering standards

- Python 3.12+
- `ruff` for linting/formatting
- `mypy` for type checking
- `pytest` for tests
- `httpx` for HTTP
- `pydantic` for typed models
- `duckdb` and `pyarrow` for local analytical storage
- structured logging where useful

## Data integrity rules

1. Never mutate a raw source file.
2. Every normalized record must retain enough source identifiers to trace it back to raw data.
3. Timestamp conversion must be tested.
4. Numeric prices and sizes should use `Decimal` at parsing/accounting boundaries when precision matters.
5. Duplicate detection must be deterministic.
6. Unknown fields may be retained, but undocumented semantic assumptions must not be invented.
7. If the API conflicts with documentation, capture the response and open a clearly documented issue/TODO rather than forcing it into the expected schema.

## Definition of done for Milestone 1

A pull request is not complete until:

- tests pass;
- type checking passes;
- linting passes;
- the collector can save raw payloads;
- normalized records can be written and reloaded;
- validation emits a useful summary;
- README instructions remain accurate.
