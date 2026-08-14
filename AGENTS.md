# Agent Instructions

Read `docs/RESEARCH_PLAN.md` for the overall project direction, `docs/MILESTONE_2_SPEC.md` for forensic reconstruction, `docs/EMPIRICAL_PAIR_SENSITIVITY_SPEC.md` for pair-sensitivity accounting, `docs/EMPIRICAL_TIMING_ROBUSTNESS_SPEC.md` for replicated timing robustness, and `docs/MILESTONE_3_REGIME_ANALYSIS_SPEC.md` for the current milestone.

## Current scope

Milestone 2 forensic reconstruction, bounded pair-sensitivity analysis, and the seven-window timing-robustness phase are complete and merged. The project is now in **Milestone 3: regime analysis and interpretable feature modeling**.

Reuse the existing collectors, raw storage, normalization, validation, DuckDB/Parquet, canonical ledger, inventory reconstruction, bounded BTC 5-minute cohort selection, FIFO/LIFO/weighted-average pair accounting, latency analysis, market-time analysis, transaction-hash diagnostics, and CI/workflow infrastructure rather than replacing them.

Milestone 3 is explicitly authorized to add timestamp-safe feature reconstruction, independently sourced BTC reference data, interpretable statistical/ML models, date-held-out evaluation, calibration, feature importance, and predeclared ablations as defined in `docs/MILESTONE_3_REGIME_ANALYSIS_SPEC.md`.

## Current empirical baseline

The prior robustness phase found both predeclared timing hypotheses replicated across seven independent six-hour windows:

1. FIFO pair formation with a 61-120 second complementary-fill lag was below $1 across all adequately sized windows.
2. FIFO pair formation during market seconds 100-199 was below $1 in six of seven adequately sized windows, with all leave-one-window-out pooled estimates below $1.

These historical results motivate Milestone 3 but must not be treated as proof of future profitability.

## Current objectives

1. Build deterministic feature tables aligned to canonical FIFO pair events.
2. Add inventory-state features using only information observable at or before each row timestamp.
3. Add independently sourced BTC state features with exact UTC alignment and no future-candle leakage.
4. Establish timing-only statistical baselines before any more complex model.
5. Evaluate inventory and BTC feature groups incrementally via predeclared ablations.
6. Use leave-one-day-out and/or walk-forward validation; random row-level claim-grade splits are prohibited.
7. Report negative results and unstable relationships rather than tuning them away.
8. Determine whether regime variation is explainable enough to justify a later simulation/backtesting milestone.

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
- Never discard expensive markets or windows because they weaken an apparent edge.
- Keep existing cohort and SELL-exclusion rules consistent across windows and methods.
- Add deterministic tests for feature timestamp safety and aggregation rules.
- Keep secrets and private wallet material out of source control.
- Update documentation when behavior changes.
- Every predictive feature must have source, timestamp semantics, lookback, and null behavior documented in a feature manifest.
- Retrospective-only fields must be explicitly marked and excluded from model matrices.

## Authorized analytical models

Milestone 3 may use:

- regularized linear regression;
- logistic regression;
- shallow decision trees;
- conservatively regularized random forests or gradient-boosted trees;
- a small multilayer perceptron only after simpler tabular baselines and leakage checks are complete.

A neural network is not the default. Any complex model must be benchmarked against timing-only and transparent statistical baselines.

## Prohibited in Milestone 3

Do not implement:

- live trading;
- order submission;
- wallet signing;
- private-key storage;
- autonomous trading;
- capital-allocation automation;
- production deployment of a discovered rule;
- claims of future profitability from historical model results;
- optimization against a live account;
- LLM/agent-based statistical prediction that obscures feature lineage or evaluation.

LangGraph or LLM agents are not needed for the predictive core of this milestone. They may be considered later for research orchestration only after deterministic analytical pipelines exist.

## Leakage rules

No predictive feature may contain information from after its row timestamp. Specifically prohibit:

- settlement/winner information;
- future BTC observations;
- later trader fills;
- eventual market inventory;
- future paired quantity;
- market-end VWAP or prices;
- final residual inventory;
- any full-market aggregate unavailable at the timestamp.

Feature tests must verify that appending future observations cannot change already-computed historical feature rows.

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
5. Numeric prices, sizes, costs, and P&L must avoid binary floating-point accounting where accounting precision matters.
6. Duplicate detection must be deterministic and its limitations documented.
7. Unknown or conflicting API semantics must be surfaced as validation failures/TODOs rather than guessed.
8. A market or window may only be treated as complete when its source windows/pages can be shown to have exhausted normally without unresolved ceiling/gap warnings.
9. Pairing calculations and feature construction must never use future information to improve apparent historical acquisition cost or model performance.
10. FIFO remains the primary lot-matching baseline; LIFO is sensitivity only.
11. Random row-level train/test splitting is not claim-grade evidence because adjacent markets/events are temporally dependent.
12. Model selection must not use the final held-out period repeatedly.
13. Public one-second Polymarket timestamps do not justify claims about sub-second fill ordering.

## Definition of done for Milestone 3

A pull request is not complete until:

- all CI checks pass;
- feature construction is deterministic and timestamp-safe;
- BTC alignment/provenance is explicit;
- a machine-readable feature manifest exists;
- timing-only baselines are reported;
- inventory and BTC feature groups are tested via fixed ablations;
- date-held-out or walk-forward results are reported;
- leakage invariance tests pass;
- negative/unstable results are retained;
- model limitations distinguish explanatory historical relationships from future tradability;
- no live-trading capability is added.