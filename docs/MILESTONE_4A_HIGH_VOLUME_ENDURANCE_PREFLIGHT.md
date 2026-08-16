# Milestone 4A High-Volume Endurance Preflight

## Purpose

This preflight is a disposable persistence endurance gate for the second Milestone 4A frozen prospective launch. It exists because the first live launch exposed an event-store scaling defect only after the durable log grew to tens of thousands of events.

The preflight does not contact Polymarket, Coinbase, Gamma, or any other API. It does not load frozen artifacts, create an `evaluation_run_start`, run models, construct Stage 3G features, form live pairs, bind scores, or write to a real evaluation log.

## Safety boundary

The CLI requires a caller-supplied disposable NDJSON path and refuses to run if that path already exists. Use a dedicated endurance directory that is separate from both the sealed `m4a-frozen-20260815` runtime and any reserved second-launch runtime.

The generated records use run ID `m4a-endurance-disposable` and source `m4a-endurance-preflight`. They are synthetic persistence probes only and must never be copied into a prospective evaluation log.

## Launch gate

The default run appends 70,000 fully durable NDJSON events, exceeding the approximate event-count regime where the first launch became CPU-bound. It records median append latency over the first and last 500 events, then closes and reopens the event store so restart must perform its full continuity scan.

A passing report requires all of the following:

- restart recovers exactly the requested next sequence;
- a post-restart continuity append succeeds at that exact sequence;
- the late-window median append latency is no more than 5x the early-window median;
- the late-window median append latency is no more than 50 ms.

The thresholds are intentionally generous enough to tolerate normal filesystem and `fsync` variance while still detecting the original full-log-rescan regression, whose cost grows with accumulated log size.

## Windows PowerShell run

Run this only from a checkout containing the merged endurance harness, with the failed first frozen task stopped and disabled.

```powershell
$ENDURANCE_ROOT = "C:\Users\bradg\OneDrive\Documents\GitHub\Artifacts\PolymarketEdgeLab\m4a-endurance-preflight"
$ENDURANCE_LOG = "$ENDURANCE_ROOT\event-store-70000.ndjson"
$ENDURANCE_REPORT = "$ENDURANCE_ROOT\report.json"

New-Item -ItemType Directory -Force -Path $ENDURANCE_ROOT | Out-Null

python scripts/preflight_m4a_endurance.py `
  --event-log $ENDURANCE_LOG `
  --output $ENDURANCE_REPORT
```

The command exits 0 when `ready` is true and exits 1 when a launch-gate threshold fails. Preserve the JSON report for the second-launch handoff, but the disposable NDJSON may be archived separately or deleted after review.

## Interpretation

`early_median_append_ms` and `late_median_append_ms` test steady-state persistence scaling. `late_to_early_median_ratio` is the primary regression signal for the PR #33 root cause. `restart_scan_seconds` is reported separately because a full continuity scan at process start is expected and bounded to restart rather than every append.

Passing this preflight is necessary but not sufficient for relaunch. After it passes, run the formal frozen-evaluation preflight again using a fresh run ID, a fresh non-existent evaluation-log path, the frozen artifacts, and the repository commit that will remain pinned for the second prospective run.
