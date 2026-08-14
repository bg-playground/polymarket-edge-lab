# Agent Instructions

Read `docs/RESEARCH_PLAN.md` for the overall project direction and `docs/MILESTONE_2_SPEC.md` for the current milestone.

## Current scope

Work on **Milestone 2: live-data validation and forensic reconstruction of a target Polymarket trader**.

Milestone 1 is complete and merged into `main`. Reuse its collectors, raw-storage, normalization, validation, DuckDB/Parquet, and CI infrastructure rather than replacing them.

Do not move ahead to strategy inference, backtesting, machine learning, LangGraph, or live trading unless the repository owner explicitly changes this file.

## Milestone 2 objectives

1. Live-validate the public Data API against a real target account.
2. Resolve and persist the verified proxy-wallet/account identity for `nagi777`.
3. Acquire the complete obtainable public trade history using maker-inclusive, time-windowed pagination.
4. Produce a trustworthy chronological per-market trade ledger.
5. Reconstruct UP/DOWN inventory over time for binary markets.
6. Separate paired inventory from directional residual inventory.
7. Calculate acquisition cost, paired cost, gross complete-set edge, and market-level realized economics under documented accounting rules.
8. Produce a machine-readable and human-readable forensic report that tests the initial public claims without assuming they are true.

## Required behavior

- Use official/current public Polymarket interfaces and verify live behavior before hard-coding uncertain assumptions.
- Preserve raw responses before transforming them.
- Keep all transformations reproducible and deterministic.
- Use UTC internally for timestamps.
- Use `Decimal` for prices, sizes, costs, and accounting boundaries.
- Keep exact token/asset IDs and condition/market IDs.
- Treat maker-inclusive collection (`takerOnly=false`) as mandatory for forensic completeness.
- Detect and report gaps, duplicate ambiguities, rejected rows, and any window that cannot be proven complete.
- Do not silently repair ambiguous records.
- Keep raw source provenance traceable from every reconstructed result.
- Add tests for every inventory and accounting rule.
- Prefer explicit accounting conventions (weighted average and FIFO sensitivity) over optimized/cherry-picked matching.
- Keep secrets and private wallet material out of source control.
- Update documentation when behavior changes.

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
- simulated or forecast profitability claims;
- automatic execution based on reconstructed behavior.

## Engineering standards

- Python 3.12+
- `ruff` for linting/formatting
- `mypy` for type checking
- `pytest` for tests
- `httpx` for HTTP
- `pydantic` for typed models
- `duckdb` and `pyarrow` for analytical storage
- structured logging where useful

## Data integrity rules

1. Never mutate a raw source file.
2. Every normalized or reconstructed record must retain enough identifiers to trace it back to source data.
3. Live-verified API facts must be documented separately from assumptions.
4. Timestamp conversion must remain tested and plausibility-checked.
5. Numeric prices, sizes, costs, and P&L must avoid binary floating-point accounting.
6. Duplicate detection must be deterministic and its limitations documented.
7. Unknown or conflicting API semantics must be surfaced as validation failures/TODOs rather than guessed.
8. A market may only be marked `complete_history=true` when its source windows/pages can be shown to have exhausted normally without unresolved ceiling/gap warnings.
9. Pairing calculations must never use future information to improve apparent historical acquisition cost.
10. Optimized lot matching may be reported only as a clearly labeled theoretical sensitivity bound, never as the primary realized result.

## Definition of done for Milestone 2

A pull request is not complete until:

- all CI checks pass;
- the live API response shape and timestamp unit have been observed and documented;
- the target `nagi777` account/proxy wallet is verified from public evidence and configurable rather than buried in code;
- a real sample collection runs end to end;
- the reconstruction engine passes deterministic unit tests;
- per-market inventory trajectories can be produced from chronological fills;
- paired versus directional exposure is calculated under documented definitions;
- pair-cost and gross-edge statistics are calculated with explicit accounting conventions;
- claim-validation output clearly distinguishes measured, unsupported, and inconclusive claims;
- incomplete history or unresolved data-quality issues cause visible warnings and prevent false completeness claims;
- README/documentation contains exact commands for the first full `nagi777` forensic run.
