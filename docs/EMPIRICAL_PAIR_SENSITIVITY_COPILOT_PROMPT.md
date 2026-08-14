# Copilot / Codex Implementation Prompt

Read `AGENTS.md`, `docs/RESEARCH_PLAN.md`, `docs/MILESTONE_2_SPEC.md`, and `docs/EMPIRICAL_PAIR_SENSITIVITY_SPEC.md` before changing code.

Implement the empirical pair-sensitivity and latency phase exactly as specified in `docs/EMPIRICAL_PAIR_SENSITIVITY_SPEC.md`.

## Context

The repository already contains:

- live-validated maker-inclusive Polymarket trade collection;
- verified `nagi777` proxy wallet configuration;
- deterministic normalized storage and canonical ledgers;
- inventory reconstruction;
- bounded fully-contained BTC 5-minute cohort selection;
- chronological FIFO complementary BUY-lot pair formation;
- within-second ordering sensitivity;
- a reproducible bounded GitHub Actions workflow.

Do not replace those components. Extend them cleanly.

The current reference bounded result is approximately 102.6472c quantity-weighted FIFO pair cost versus the public claim of 98.43c. The purpose of this task is to determine whether that discrepancy is robust across predeclared accounting definitions and whether profitable pair formation is concentrated by latency or time within the 5-minute market.

## Required implementation

1. Generalize pair matching so FIFO remains primary and LIFO is implemented as an explicit sensitivity method.
2. Implement weighted-average inventory accounting for incremental increases in paired inventory using only information available at each event time.
3. Produce a side-by-side accounting-method comparison over the identical eligible cohort.
4. Produce per-market pair-cost distributions and aggregate percentiles/statistics.
5. Add the exact complementary-fill latency buckets defined in the spec.
6. Add 30-second time-within-market buckets plus early/middle/late bands.
7. Add a transaction-hash grouping diagnostic without claiming transaction hash equals order identity.
8. Preserve and report one-second timestamp ordering sensitivity.
9. Generate machine-readable and Markdown reports and include them in the bounded workflow artifact.
10. Add deterministic unit tests for all new accounting rules and bucket boundaries.
11. Run ruff check, ruff format --check, mypy, pytest, and the bounded real-data workflow if GitHub Actions/network access permits.

## Guardrails

- Never optimize matching to get closer to 98.43c.
- Never drop high-cost pair events to improve the result.
- Do not use future information.
- Keep Decimal accounting throughout.
- Keep the exact same bounded cohort inclusion rules across accounting methods.
- Label LIFO and any theoretical bounds as sensitivities, not realized truth.
- Do not infer trading intent, maker strategy, predictive signals, or profitability beyond the measured execution-price accounting.
- Do not add ML, neural networks, LangGraph, LLM-agent orchestration, backtesting, or live trading.

## Deliverable

Update this branch/PR with implementation, tests, documentation, and reproducible reports/workflow integration. In the PR summary, state the empirical results for FIFO, LIFO, weighted-average accounting, latency buckets, market-time buckets, and transaction-hash diagnostic, including whether the full bounded cohort supports or fails to support the public 98.43c claim under each standard method.
