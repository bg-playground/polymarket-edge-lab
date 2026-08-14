# Copilot / Codex Implementation Prompt

Read `AGENTS.md`, `docs/RESEARCH_PLAN.md`, `docs/MILESTONE_2_SPEC.md`, `docs/EMPIRICAL_PAIR_SENSITIVITY_SPEC.md`, and `docs/EMPIRICAL_TIMING_ROBUSTNESS_SPEC.md` before changing code.

Implement the empirical timing-robustness phase exactly as specified in `docs/EMPIRICAL_TIMING_ROBUSTNESS_SPEC.md`.

## Context

The repository already contains a verified `nagi777` account, maker-inclusive public trade collection, deterministic normalized storage, canonical ledgers, bounded fully-contained BTC 5-minute cohort selection, FIFO/LIFO/weighted-average pair accounting, latency buckets, market-time buckets, transaction-hash diagnostics, and a reproducible bounded GitHub Actions workflow.

Do not replace those components. Generalize and orchestrate them for multiple independent windows.

The primary out-of-sample hypotheses are frozen before implementation:

1. FIFO pair formation with 61-120 second complementary-fill lag remains below $1.
2. FIFO pair formation during market seconds 100-199 remains below $1.

Do not change those hypotheses or bucket definitions after observing expanded data.

## Required implementation

1. Add deterministic generation/validation of non-overlapping UTC study windows.
2. Support a default primary study of at least 7 calendar days x 6 hours/day when history permits.
3. Reuse existing collection and reconstruction for each window and retain completeness evidence separately.
4. Produce per-window and pooled FIFO/LIFO/weighted-average metrics.
5. Produce per-window latency and market-time tables using the existing exact buckets.
6. Implement primary-hypothesis robustness summaries, including pooled quantity-weighted estimates, equal-window means, medians, fraction of adequate windows below $1, leave-one-window-out results, and cumulative chronological estimates.
7. Implement the conservative classifications from the spec: replicated, mixed, not_replicated, insufficient_data.
8. Preserve all secondary bucket results as descriptive only.
9. Add machine-readable + Markdown reporting and include evidence in a GitHub Actions artifact.
10. Add deterministic tests for window construction, aggregation, classification, leave-one-out, cumulative estimates, incomplete windows, thresholds, and Decimal precision.
11. Run ruff check, ruff format --check, mypy, pytest, and the live robustness workflow if network access permits.

## Guardrails

- Never overlap windows in the primary panel.
- Never redefine the primary timing hypotheses after seeing results.
- Never drop high-cost windows or markets to improve the result.
- Never use future fills in pair formation.
- Keep Decimal accounting.
- Keep existing cohort and SELL-exclusion rules consistent.
- Do not infer causal strategy intent or future profitability.
- Do not add BTC predictive features, ML, neural networks, LangGraph, LLM agents, backtesting, strategy optimization, or trading execution.

## Deliverable

Update this branch/PR with implementation, tests, workflow integration, and a concise empirical summary that answers whether each of the two frozen timing hypotheses replicates across the expanded independent-window study.