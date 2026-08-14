# Agent Instructions

Read `docs/RESEARCH_PLAN.md` for the overall project direction, `docs/MILESTONE_2_SPEC.md` for the forensic-reconstruction milestone, and `docs/EMPIRICAL_PAIR_SENSITIVITY_SPEC.md` for the current empirical extension.

## Current scope

Milestone 2 forensic reconstruction is implemented and the project is now in an **empirical pair-accounting sensitivity and timing-analysis checkpoint before Milestone 3**.

Reuse the existing collectors, raw storage, normalization, validation, DuckDB/Parquet, canonical ledger, inventory reconstruction, bounded BTC 5-minute cohort selection, FIFO pair-formation analysis, and CI infrastructure rather than replacing them.

The current phase is explicitly authorized to add LIFO sensitivity, incremental weighted-average pair accounting, per-market distributions, complementary-fill latency analysis, time-within-market analysis, and transaction-hash grouping diagnostics as defined in `docs/EMPIRICAL_PAIR_SENSITIVITY_SPEC.md`.

Do not move ahead to strategy inference, backtesting, machine learning, LangGraph, or live trading unless the repository owner explicitly changes this file.

## Current empirical objectives

1. Keep chronological FIFO complementary BUY-lot matching as the primary bounded historical baseline.
2. Add LIFO and weighted-average accounting as predeclared sensitivities over the identical eligible cohort.
3. Explain pair-cost variation across markets and accounting definitions.
4. Measure whether profitable pair formation is concentrated by complementary-fill lag.
5. Measure whether profitable pair formation is concentrated by time within each BTC 5-minute market.
6. Diagnose transaction-hash grouping without treating a transaction hash as an order identifier.
7. Test whether the public 98.43c pair-cost / 1.57c edge claim is robustly supported under standard definitions without optimizing toward the claim.

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
- Add tests for every inventory, accounting, and bucket-boundary rule.
- Keep identical cohort/inclusion rules across accounting methods.
- Never discard expensive pair events because they weaken an apparent edge.
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
8. A market may only be marked `complete_history=true` when its source windows/pages can be shown to have exhausted normally without unresolved ceiling/gap warnings.
9. Pairing calculations must never use future information to improve apparent historical acquisition cost.
10. FIFO remains the primary lot-matching baseline; LIFO and theoretical optimized matching may only be reported as clearly labeled sensitivities.
11. A narrow latency/time bucket matching the public claim is not evidence that the full-cohort claim is supported.
12. Public one-second timestamps do not justify claims about sub-second fill ordering.

## Definition of done for the current empirical checkpoint

A pull request is not complete until:

- all CI checks pass;
- the same bounded cohort is used across all accounting methods;
- FIFO, LIFO, and weighted-average results are reported side by side;
- per-market distributions are reproducible;
- latency and time-within-market bucket boundaries are explicit and tested;
- transaction-hash diagnostics are labeled conservatively;
- one-second ordering sensitivity is preserved;
- machine-readable and human-readable reports are included in the bounded workflow artifact;
- the public 98.43c claim is assessed without cherry-picking or optimized matching;
- limitations clearly distinguish measured execution-price accounting from strategy inference or actual realized P&L.
