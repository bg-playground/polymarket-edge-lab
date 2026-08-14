# Agent Instructions

Read `docs/RESEARCH_PLAN.md` for the overall project direction, `docs/MILESTONE_2_SPEC.md` for the forensic-reconstruction milestone, `docs/EMPIRICAL_PAIR_SENSITIVITY_SPEC.md` for the merged sensitivity phase, and `docs/EMPIRICAL_TIMING_ROBUSTNESS_SPEC.md` for the current phase.

## Current scope

Milestone 2 forensic reconstruction and the first bounded pair-sensitivity analysis are implemented. The project is now in an **out-of-sample empirical timing-robustness phase before Milestone 3**.

Reuse the existing collectors, raw storage, normalization, validation, DuckDB/Parquet, canonical ledger, inventory reconstruction, bounded BTC 5-minute cohort selection, FIFO/LIFO/weighted-average pair accounting, latency analysis, market-time analysis, transaction-hash diagnostics, and CI/workflow infrastructure rather than replacing them.

The current phase is explicitly authorized to expand those analyses across multiple independent, non-overlapping historical windows and to compute robustness/stability statistics as defined in `docs/EMPIRICAL_TIMING_ROBUSTNESS_SPEC.md`.

Do not move ahead to strategy inference, backtesting, machine learning, LangGraph, or live trading unless the repository owner explicitly changes this file.

## Frozen primary empirical hypotheses

1. FIFO pair formation with a 61-120 second complementary-fill lag remains below $1 across the expanded independent-window sample.
2. FIFO pair formation during market seconds 100-199 remains below $1 across the expanded independent-window sample.

These hypotheses and their bucket definitions must not be changed after observing expanded data.

## Current empirical objectives

1. Collect and reconstruct a materially larger set of independent, non-overlapping windows.
2. Preserve per-window completeness evidence and exact UTC boundaries.
3. Reproduce full-cohort FIFO/LIFO/weighted-average accounting for every window.
4. Reproduce the existing fixed latency and market-time bucket metrics for every window.
5. Evaluate the two frozen timing hypotheses with pooled, equal-window, leave-one-out, and cumulative statistics.
6. Classify each primary hypothesis conservatively as replicated, mixed, not_replicated, or insufficient_data under the predeclared rules.
7. Keep all other timing buckets descriptive secondary results only.

## Required behavior

- Use official/current public Polymarket interfaces and verify live behavior before hard-coding uncertain assumptions.
- Preserve raw responses before transforming them.
- Keep all transformations reproducible and deterministic.
- Use UTC internally for timestamps.
- Use `Decimal` for prices, sizes, costs, and accounting boundaries.
- Keep exact token/asset IDs and condition/market IDs.
- Treat maker-inclusive collection (`takerOnly=false`) as mandatory for forensic completeness.
- Detect and report gaps, duplicate ambiguities, rejected rows, incomplete windows, and any window that cannot be proven complete.
- Do not silently repair ambiguous records.
- Keep raw source provenance traceable from every reconstructed result.
- Never overlap windows in the primary study panel.
- Never discard expensive markets or windows because they weaken an apparent edge.
- Keep existing cohort and SELL-exclusion rules consistent across windows and methods.
- Add deterministic tests for all aggregation, threshold, and classification rules.
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
- underlying-asset predictive signals;
- strategy optimization;
- backtesting;
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
8. A market or window may only be treated as complete when its source windows/pages can be shown to have exhausted normally without unresolved ceiling/gap warnings.
9. Pairing calculations must never use future information to improve apparent historical acquisition cost.
10. FIFO remains the primary lot-matching baseline; LIFO is sensitivity only.
11. The primary timing hypotheses are frozen before expanded data is observed.
12. A secondary bucket that appears attractive in this phase remains descriptive and may not be promoted without a new out-of-sample phase.
13. Public one-second timestamps do not justify claims about sub-second fill ordering.

## Definition of done for the current empirical checkpoint

A pull request is not complete until:

- all CI checks pass;
- multiple independent non-overlapping windows are collected and their completeness is explicit;
- achieved study size and deviations from the target design are documented;
- per-window FIFO/LIFO/weighted-average results are reproducible;
- the exact existing latency and market-time buckets are reused unchanged;
- the two frozen timing hypotheses are evaluated using the predeclared robustness statistics;
- leave-one-window-out and cumulative estimates are reported;
- replication classifications follow the spec without discretionary overrides;
- machine-readable and human-readable reports are included in the workflow artifact;
- limitations clearly distinguish historical execution-price robustness from strategy inference or future profitability.