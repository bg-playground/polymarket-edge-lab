# Project State Before Milestone 4A Frozen Evaluation

## Purpose

This document is the durable handoff for continuing Polymarket Edge Lab immediately after completion of the Milestone 4A Live Shadow Engine implementation and immediately before the frozen prospective evaluation is launched.

It is intended to be sufficient context for a fresh engineering conversation. The repository and frozen specifications remain authoritative if this summary and code ever disagree.

**Important boundary:** the real Milestone 4A frozen evaluation has **not** been intentionally launched by this handoff. The next implementation item is PR #31, a preflight / launch-readiness slice. PR #31 must not accidentally create the real evaluation event log or start the 14–28 day evaluation clock.

The system remains strictly read-only and shadow-only. It must not sign, submit, cancel, route, or simulate-submit orders and must not expose capital.

---

## Repository state at handoff

Repository: `bg-playground/polymarket-edge-lab`

PR #30, **Milestone 4A: freeze evaluation run control and prospective reporting**, was merged into `main` with merge commit:

`9fe3b895ff4645509caddcb693adcb189da3cad6`

This was the known `main` state immediately before this handoff document was added. The commit containing this document is necessarily later and should be inspected before PR #31 begins. Do not assume the SHA above is the final evaluation commit.

Before making changes in a new conversation:

1. inspect current `main`;
2. inspect this handoff;
3. inspect `docs/MILESTONE_4A_LIVE_SHADOW_ENGINE_SPEC.md`;
4. inspect the implementation named below;
5. verify all relevant CI is green;
6. only then create the PR #31 branch.

---

## Stage 3G result that Milestone 4A is validating

Stage 3G passed its strict pre-event external validation gate. Its primary frozen candidate is:

`hgb_all_pre_event`

The primary model uses the exact Stage 3G causal pre-event feature order:

1. `elapsed_seconds`
2. `seconds_remaining`
3. `up_inventory`
4. `down_inventory`
5. `paired_inventory`
6. `residual_inventory`
7. `inventory_imbalance`
8. `seconds_since_last_up_fill`
9. `seconds_since_last_down_fill`
10. `fill_count_15s`
11. `fill_count_30s`
12. `fill_count_60s`
13. `fill_qty_15s`
14. `fill_qty_30s`
15. `fill_qty_60s`
16. `side_switches_60s`
17. `cumulative_paired_quantity`
18. `same_second_fill_count`
19. `btc_return_60s`
20. `btc_return_120s`
21. `btc_absolute_return_60s`
22. `btc_return_since_market_start`
23. `btc_range_since_market_start`

Frozen Stage 3G model parameters and training semantics are defined in the Milestone 4A spec. Do not refit, reweight, recalibrate, change features, or select thresholds from Milestone 4A live outcomes.

Frozen comparators are:

- `hgb_timing_inventory`
- `linear_timing_inventory`
- `hgb_timing_inventory_btc60`

The complete Stage 3G August 7–13, 2026 discovery panel, restricted to 12:00–18:00 UTC, is the frozen training source.

---

## Frozen Milestone 4A contract

Authoritative specification:

`docs/MILESTONE_4A_LIVE_SHADOW_ENGINE_SPEC.md`

Core frozen domain:

- target public account: `0xbf337426aa856996b8bb79b238345dd1a0276bf7`
- eligible BTC 5-minute UP/DOWN binary markets only
- advancement window: 12:00–18:00 UTC
- target-account polling cadence: 1 Hz
- prospective feature/scoring cadence: 1 Hz
- BTC semantics: Coinbase BTC-USD 60-second candles, causal only after candle close
- BTC stale gate: latest causal close more than 120 seconds old => unscorable
- target collector continuously failing/disconnected more than 5 seconds => unscorable
- ambiguity, inconsistent token mapping, non-idempotent duplicate, or impossible state => fail closed / quarantine rather than guess

Any change during the real evaluation that could affect feature values, prediction timing, label binding, model outputs, evaluation inclusion, or advancement criteria requires explicit versioning and restarts the affected prospective window.

---

## Milestone 4A implementation history

The following merged PRs built the current Live Shadow Engine. Inspect the code rather than relying only on this prose if exact behavior matters.

- **PR #16** — froze the Milestone 4A Live Shadow Engine specification and initial contract.
- **PR #17** — froze/serialized the Stage 3G primary and comparator model artifacts and artifact metadata/fingerprints.
- **PR #18** — established the initial live-shadow implementation foundation following the frozen spec.
- **PR #19** — added append-only event contracts and deterministic online state/replay foundation.
- **PR #20** — hardened the bounded online state machine.
- **PR #21** — added the live target-account collector and raw observation persistence.
- **PR #22** — added live market eligibility, BTC 5-minute market metadata, and deterministic UP/DOWN token mapping.
- **PR #23** — integrated market metadata with target fills so only mapped/eligible fills are admitted as normalized fills.
- **PR #24** — connected admitted normalized fills to `MarketOnlineState` with durable pair-formation/quarantine output.
- **PR #25** — added live BTC-USD ingestion with frozen Stage 3G 60-second candle semantics.
- **PR #26** — added the causal live Stage 3G feature-vector builder and frozen stale/unscorable gates.
- **PR #27** — loaded frozen Stage 3G primary/comparator artifacts and emitted durable shadow predictions.
- **PR #28** — added prospective outcome labels and strict score-to-pair binding.
- **PR #29** — completed live runner scoring integration and bounded end-to-end no-API replay/audit.
- **PR #30** — added frozen evaluation run control and deterministic prospective reporting.

When exact PR scope is important, query GitHub for the merged PR rather than treating this list as a substitute for the diff.

---

## Current live pipeline

Primary runner:

`scripts/run_m4a_target_collector.py`

At the PR #30 state it constructs and runs:

1. `AppendOnlyEventStore`
2. frozen evaluation preflight/start logic when `--frozen-evaluation` is supplied
3. `LiveMarketMetadataResolver`
4. `LiveTargetAccountCollector`
5. `LiveStateProcessor`
6. `ProspectiveOutcomeBinder`
7. `LiveBtc60Collector`
8. `LiveStage3GFeatureBuilder`
9. `LiveShadowScorer`
10. `LiveFeatureCadence`

The runner requires `--artifact-dir`. Frozen evaluation mode additionally requires `--frozen-evaluation` and `--repository-commit`.

Do not use the real frozen evaluation event-log path while developing or testing PR #31.

---

## Append-only / replay principles

The event log is append-only. Online behavior is reconstructed from durable events rather than mutable hidden state.

Important event classes include, among others:

- raw target observations / health
- normalized fills and fill admission
- market metadata/mapping
- BTC candles / revisions
- state application and quarantine
- pair formation
- feature snapshots / unscorable ticks
- score attempts and predictions
- outcome labels
- score bindings
- replay/audit records
- `evaluation_run_start`

The exact event schema is authoritative in the repository.

PR #29 added bounded replay auditing that does not consult live APIs. It reconstructs feature snapshots from their original append-log prefix, recomputes frozen predictions from artifacts, checks pair/outcome coverage, and independently re-derives strict prospective bindings.

Before the real frozen run begins, PR #31 should exercise this bounded replay path using disposable fixture/test data and verify that the audit succeeds.

---

## Online state and pair formation

The online state machine follows the Stage 3G FIFO complementary-pair accounting semantics. Eligible normalized target fills are applied deterministically. Ambiguous or impossible transitions are quarantined rather than guessed.

`pair_formation` records are durable and include the information required for later outcome labeling, including pair cost, paired quantity, lag, completing trade identity, and source/receive timing.

BUY-only state semantics used by the Stage 3G feature builder must not be casually changed. SELL observations do not retroactively redefine the frozen Stage 3G model input semantics.

---

## Causal live feature semantics

`LiveStage3GFeatureBuilder` reconstructs the frozen Stage 3G feature vector using only information causally available at the snapshot's recorded append-log boundary.

Every 1 Hz evaluation tick must produce either a scorable feature snapshot or an explicit unscorable record/reason.

Important gates include:

- eligible active market and valid UP/DOWN mapping
- `0 <= elapsed_seconds < 300`
- healthy/non-quarantined state
- causal BTC reference exists
- BTC freshness within frozen limit
- target collector freshness within frozen limit
- no unresolved ordering ambiguity or impossible state

Late-arriving information must never mutate an already durable prospective feature snapshot or prediction.

---

## Frozen prediction semantics

`LiveShadowScorer` loads exactly four frozen Stage 3G models after validating the artifact manifest and file fingerprints.

Primary:

- `hgb_all_pre_event`

Comparators/diagnostic:

- `hgb_timing_inventory`
- `linear_timing_inventory`
- `hgb_timing_inventory_btc60`

Predictions persist model outputs plus artifact fingerprints and causal/input provenance. A score is only useful prospectively after it is durably appended.

`event_conditioned_reconstruction=true` predictions, if produced for diagnostics, are permanently excluded from advancement metrics.

---

## Strict prospective score-to-outcome binding

This rule is critical and must not be loosened.

When a target fill completes one or more FIFO pair rows, each resulting pair is labeled with:

- `pair_cost`
- `favorable = pair_cost < 1.0`
- `paired_shares`
- label-only lag information

For advancement, select only the latest advancement-eligible prediction for that market whose **durable prediction timestamp is strictly earlier than the beginning of the completing target fill's reported source second**:

`score_durable_epoch_ms < target_fill_timestamp_seconds * 1000`

A prediction created in the same reported source second is excluded.

The implemented binder additionally requires the candidate prediction's append sequence to precede the pair event, preventing retroactive binding of a later-appended record carrying an anomalously old wall-clock timestamp.

If nothing qualifies, persist:

`unbound_no_strictly_prior_score`

If one completing fill produces multiple FIFO pair rows, the same latest qualifying prediction may bind to each distinct row. A later prediction must never replace an already bound score after the outcome is known.

---

## Bounded replay / parity audit

Relevant implementation:

`src/polymarket_edge_lab/shadow/bounded_replay.py`

CLI:

`scripts/audit_m4a_bounded_replay.py`

The audit is intended to prove no-API deterministic reconstruction of the bounded live chain. It:

- runs arrival-time replay;
- rebuilds persisted feature snapshots using only records through each original `as_of_sequence`;
- checks frozen feature values/provenance;
- reloads frozen artifacts and recomputes prediction outputs;
- verifies numeric prediction parity;
- reconstructs outcome labels;
- re-derives strict score binding;
- requires one-to-one pair/outcome/binding coverage.

PR #31 preflight should use this capability without touching a real evaluation log.

---

## Frozen evaluation run control

Relevant implementation:

`src/polymarket_edge_lab/shadow/evaluation.py`

Schema:

`m4a-frozen-evaluation-v1`

A real frozen evaluation begins only when `start_frozen_evaluation()` appends the immutable `evaluation_run_start` event at **sequence 0 of an empty event log**.

The start record freezes at minimum:

- `frozen_evaluation=true`
- run ID
- repository commit supplied to the runner
- target account
- 12:00–18:00 UTC evaluation domain
- exact 1-second target polling cadence
- exact 1-second feature cadence
- artifact manifest hash and per-model artifact/preprocessing fingerprints and training metadata

`verify_frozen_evaluation()` fails closed on run ID, repository commit, target account, cadence, or artifact-manifest drift.

**Operational warning:** the existing runner will create `evaluation_run_start` automatically when invoked with `--frozen-evaluation` against an empty log. Therefore PR #31 must use a disposable log and must not invoke frozen mode against the path reserved for the real evaluation until the explicit launch decision is made.

---

## Prospective reporting foundation

Relevant implementation:

`src/polymarket_edge_lab/shadow/reporting.py`

CLI:

`scripts/report_m4a_frozen_evaluation.py`

Schema:

`m4a-prospective-report-v1`

The reporter reads only records after the frozen sequence-zero start and restricts advancement metrics to the frozen 12:00–18:00 UTC domain.

It computes descriptive frozen quantities including:

- total eligible pair rows in-domain
- prospectively bound and unbound rows
- bound coverage rate
- bound paired-share weight
- paired-shares-weighted MAE for primary/comparators
- paired-shares-weighted Brier for primary/comparators
- 10-bin weighted calibration summaries
- reportable-day counts
- 14/28-day horizon progress
- BTC age diagnostics
- target-source age diagnostics
- score-write latency diagnostics
- replay-audit status

Current constants in the PR #30 implementation include:

- reportable day: at least 500 bound rows
- minimum bound rows: 20,000
- minimum reportable days: 10
- minimum elapsed days: 14
- maximum horizon: 28 days

These values must be checked against the frozen specification before any future change. Do not select or optimize thresholds from live results.

The reporter is intentionally descriptive and should not be expanded into a newly invented live-data-selected PASS/FAIL criterion.

---

## CI / repository hygiene learned during Milestone 4A

The normal CI gates repeatedly exercised during Milestone 4A are:

- `ruff check .`
- `ruff format --check .`
- `mypy src`
- `pytest`

Ruff's formatter is authoritative. Avoid manually fighting its preferred wrapping: run/verify formatting before considering a branch ready.

Mypy is configured strictly enough to flag unused ignores and unsafe `object` conversions. Preserve explicit narrowing/conversion patterns where needed.

Recent fixes were mechanical CI fixes only; they were deliberately kept separate from frozen behavioral changes.

PR #31 should add tests for its preflight/readiness behavior and should pass all existing CI without changing model, feature, pair, binding, or reporting semantics.

---

## Next implementation: PR #31

Proposed title:

**Milestone 4A: frozen evaluation preflight and launch readiness**

Suggested branch:

`agent/m4a-frozen-evaluation-preflight`

PR #31 should be deliberately small and operational. Its purpose is to prove that the frozen engine is ready to launch, **not to start the actual evaluation**.

Recommended scope:

1. Add a machine-readable preflight result/report.
2. Verify the exact candidate repository commit intended for launch.
3. Verify the frozen artifact directory and all manifest/artifact fingerprints.
4. Verify frozen target account and 1 Hz target/feature configuration.
5. Verify event-log destination is writable and, for a new frozen run, empty.
6. Verify UTC wall-clock assumptions and monotonic-clock availability/sanity.
7. Exercise startup and restart validation using a disposable event log.
8. Run bounded replay/audit on fixture/disposable data and require success.
9. Perform read-only connectivity/readiness checks for the required external sources (target-account Polymarket Data API, market metadata source, and BTC source) without writing those observations into the future real evaluation log.
10. Produce explicit fail-closed reason codes for failed readiness checks.
11. Document the exact launch command/procedure and the rule that the real evaluation log must be fresh/empty before sequence-zero start.
12. Keep all checks shadow-only/read-only; do not add execution capability.

The exact implementation should be chosen after inspecting current code and tests. Do not mechanically implement this list if repository state suggests a cleaner design that satisfies the same frozen contract.

### Explicit non-goals for PR #31

PR #31 must not:

- launch the actual frozen evaluation;
- create the real evaluation event log;
- start the 14–28 day clock;
- retrain or modify models;
- change features or feature order;
- alter stale-data thresholds;
- alter market eligibility;
- alter FIFO pair accounting;
- alter prospective score timing;
- loosen strict score-to-outcome binding;
- change advancement inclusion rules or thresholds based on observed live outcomes;
- add order signing/submission/cancellation/routing;
- expose capital.

---

## Launch boundary after PR #31

If PR #31 merges and the real preflight passes, stop normal evaluation-affecting development before launch.

Then:

1. identify and record the exact final `main` commit to freeze;
2. verify CI is green on that commit;
3. verify frozen artifacts and manifest fingerprints;
4. choose a unique real evaluation `run_id`;
5. choose a fresh, empty durable event-log path;
6. run the preflight against the intended environment without contaminating that log;
7. explicitly approve launch;
8. start `scripts/run_m4a_target_collector.py` with `--frozen-evaluation`, the exact `--repository-commit`, frozen artifact directory, real run ID, and fresh event log;
9. confirm sequence 0 is exactly one valid `evaluation_run_start`;
10. allow prospective evidence collection to proceed without evaluation-affecting code/config changes.

Once sequence-zero `evaluation_run_start` exists in the real log, treat the prospective window as frozen. A defect or external incompatibility that can affect evaluation semantics should cause an explicit stop/version/restart decision rather than an invisible patch.

---

## Recommended opening prompt for a fresh Project conversation

Use this after switching to a new conversation inside the Polymarket Project:

> Continue the Polymarket Edge Lab project from the completed Milestone 4A Live Shadow Engine implementation. PR #30 is merged into `main`, and `docs/PROJECT_STATE_BEFORE_M4A_FROZEN_EVALUATION.md` contains the durable handoff. We are ready to build PR #31: **Milestone 4A — frozen evaluation preflight and launch readiness**. The real frozen prospective evaluation has NOT been launched yet. Before making changes, inspect the handoff document, `docs/MILESTONE_4A_LIVE_SHADOW_ENGINE_SPEC.md`, current `main`, the evaluation/run-control, bounded-replay, reporting, runner, and relevant tests. Then propose the bounded PR #31 implementation plan and proceed with implementation after confirming it preserves the frozen contract. Do not start or contaminate the real evaluation log, do not change evaluation/model/feature/binding semantics, and keep the system strictly read-only/shadow-only.

The new conversation should trust current repository state over conversational recollection and should verify merged PR/commit state before editing.
