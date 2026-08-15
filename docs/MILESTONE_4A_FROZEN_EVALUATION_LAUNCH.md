# Milestone 4A Frozen Evaluation Launch Procedure

## Purpose

This runbook defines the operational boundary between Milestone 4A launch readiness and the real frozen prospective evaluation.

The preflight is intentionally non-launching. It must not create, append to, or otherwise contaminate the event log reserved for the real evaluation. The 14–28 day prospective clock begins only when the live runner appends `evaluation_run_start` at sequence zero of the reserved empty event log.

The frozen behavioral contract remains `docs/MILESTONE_4A_LIVE_SHADOW_ENGINE_SPEC.md`. This document does not change model, feature, eligibility, FIFO accounting, stale-data, prospective timing, binding, reporting, or advancement semantics.

## Required state before launch

Run the final preflight only after PR #31 is merged and the exact launch checkout is on clean `main`.

The launch candidate must have:

- a clean Git worktree;
- an exact 40-character `HEAD` SHA selected as the frozen `repository_commit`;
- the frozen Stage 3G artifact directory and unchanged manifest/model fingerprints;
- the frozen target account `0xbf337426aa856996b8bb79b238345dd1a0276bf7`;
- exact 1-second target polling and feature cadence;
- a reserved real evaluation-log path that either does not exist or exists as a zero-byte regular file;
- a writable parent directory for that reserved log;
- working timezone-aware UTC and monotonic clocks;
- a successful disposable start/restart validation;
- a successful disposable no-API bounded replay using the frozen artifacts;
- successful read-only probes of the Polymarket target-account Data API, Polymarket Gamma market-metadata API, and Coinbase BTC-USD candle source.

Do not use a branch SHA from before PR #31 is merged as the final launch commit. Resolve the exact merged `main` SHA immediately before the final preflight and use the same SHA for launch and all restarts.

## Final preflight

From a clean checkout of the exact merged `main` candidate:

```bash
REPOSITORY_COMMIT="$(git rev-parse HEAD)"
RUN_ID="m4a-frozen-YYYYMMDD"
ARTIFACT_DIR="/absolute/path/to/frozen-stage3g-artifacts"
EVENT_LOG="/absolute/path/to/reserved/m4a-frozen-evaluation.ndjson"

python scripts/preflight_m4a_frozen_evaluation.py \
  --run-id "$RUN_ID" \
  --repository-commit "$REPOSITORY_COMMIT" \
  --repository-root . \
  --artifact-dir "$ARTIFACT_DIR" \
  --event-log "$EVENT_LOG" \
  --output /absolute/path/outside/repository/m4a-preflight.json
```

The command exits with status `0` only when every readiness check passes. A failed check is reported with an explicit fail-closed `reason_code`; status `2` means not ready.

Write the optional report outside the repository so creating the report does not dirty the launch checkout after the repository-cleanliness check.

The preflight may create and remove temporary files beside the reserved log to verify parent-directory writability. It does not create or append to the reserved evaluation log itself. Disposable evaluation-start and bounded-replay logs are created only under temporary directories and are deleted after the check.

## Launch boundary

Do not launch unless the final machine-readable preflight report has `"ready": true` and the exact repository SHA, run ID, artifact directory, and event-log path have been reviewed.

Immediately before launch, independently confirm:

```bash
test "$(git status --porcelain)" = ""
test "$(git rev-parse HEAD)" = "$REPOSITORY_COMMIT"
test ! -e "$EVENT_LOG" || test ! -s "$EVENT_LOG"
```

The real evaluation is then started explicitly with:

```bash
python scripts/run_m4a_target_collector.py \
  --run-id "$RUN_ID" \
  --event-log "$EVENT_LOG" \
  --artifact-dir "$ARTIFACT_DIR" \
  --frozen-evaluation \
  --repository-commit "$REPOSITORY_COMMIT"
```

On an empty log, this command creates the immutable `evaluation_run_start` at sequence zero and starts the real prospective window. This is the action that must not be performed during PR #31 development or testing.

## Restart procedure

A restart of the same frozen evaluation must use exactly the same:

- `RUN_ID`;
- `EVENT_LOG`;
- `ARTIFACT_DIR` contents and fingerprints;
- `REPOSITORY_COMMIT`;
- target account;
- 1-second target polling cadence;
- 1-second feature cadence.

Re-run the same live command. Because the log is no longer empty, the runner calls frozen evaluation verification rather than creating another start record. Any run-control or artifact drift fails closed.

Do not replace the repository commit with a newer code commit during the active prospective window. A change that can affect feature values, prediction timing, label binding, model outputs, evaluation inclusion, or advancement criteria requires explicit versioning and restart of the affected frozen window under the governing specification.

## Reporting and replay audit

Prospective reports remain descriptive and use the already frozen evaluation thresholds and inclusion rules. Generate them with the existing reporting CLI against the real evaluation log; do not use preflight output as a substitute for prospective reporting.

Bounded replay/audit remains no-API and deterministic. The PR #31 preflight runs a disposable synthetic chain only to prove launch readiness with the exact frozen artifacts. It does not add a `replay_audit` record to the future real evaluation log and therefore does not claim that later real-run replay has already passed.

## Safety boundary

Milestone 4A remains strictly read-only and shadow-only. Neither preflight nor launch readiness adds order signing, submission, cancellation, routing, simulated submission, or capital exposure.
