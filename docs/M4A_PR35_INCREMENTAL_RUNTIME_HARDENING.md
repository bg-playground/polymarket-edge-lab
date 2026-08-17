# Milestone 4A PR #35 — Incremental Runtime Hardening

## Incident boundary

The second frozen launch, `m4a-frozen-20260817`, is sealed as operational evidence and must not be resumed after PR #35 changes runtime code. It remained outside the 12:00–18:00 UTC advancement window while the decisive failure was diagnosed.

At roughly 86,000 durable events, both Polymarket and Coinbase began reporting `ConnectTimeout` from the live runner even though exact standalone requests from the same host and Python interpreter completed successfully in well under one second. After a genuine process replacement, the two independent sources again timed out within milliseconds of each other.

The runtime inspection identified synchronous sequence-zero scans on the shared asyncio loop:

- `LiveStateProcessor.process_pending()` reparsed the whole durable log each second.
- `ProspectiveOutcomeBinder.process_pending()` reparsed the whole durable log each second and rescanned historical predictions for pending pairs.
- `LiveShadowScorer.process_pending()` reparsed the whole durable log on feature cadence.
- feature/cadence historical reads repeatedly reparsed the NDJSON file.

PR #33 removed the analogous append-side full-log rescan. PR #35 removes the steady-state read-side NDJSON reparse while retaining one complete validation/reconstruction scan on restart.

## Frozen-contract boundary

PR #35 does not change:

- frozen target account or public source endpoints;
- target/BTC/feature polling cadences;
- market eligibility or token mapping;
- fill admission or FIFO state semantics;
- Stage 3G feature definitions/order or frozen model artifacts;
- target/BTC stale-data thresholds;
- the 12:00–18:00 UTC evaluation domain;
- the strictly-prior score-binding boundary;
- advancement/reporting semantics; or
- read-only/shadow-only operation.

The next real prospective launch must use a fresh run ID and a fresh sequence-zero log pinned to the exact merged PR #35 commit. Neither `m4a-frozen-20260815` nor `m4a-frozen-20260817` may be reused.

## Post-merge Windows runtime endurance gate

Run this gate against a new disposable path on the intended Windows/OneDrive-backed artifact filesystem before reserving another frozen run ID:

```powershell
$REPO = "C:\Users\bradg\OneDrive\Documents\GitHub\bg-playground\polymarket-edge-lab"
$ROOT = "C:\Users\bradg\OneDrive\Documents\GitHub\Artifacts\PolymarketEdgeLab\m4a-runtime-endurance-pr35"
$LOG = "$ROOT\runtime-100000.ndjson"
$REPORT = "$ROOT\report.json"

Set-Location $REPO
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONPATH = "$REPO\src"
New-Item -ItemType Directory -Force -Path $ROOT | Out-Null

Write-Host "Disposable log exists:" (Test-Path $LOG)
python scripts/preflight_m4a_runtime_endurance.py `
  --event-log $LOG `
  --output $REPORT

Get-Content $REPORT
```

The disposable event-log path must not exist before the run. The default gate uses 100,000 seeded events, 100 processing cycles, a 250 ms p95 cycle ceiling, and a 1,000 ms absolute maximum cycle ceiling.

A passing runtime endurance report is necessary but not sufficient for relaunch. After it passes, run the existing formal frozen-evaluation preflight against a fresh reserved log and the exact merged commit. Launch only if that preflight returns `ready: true` and the reserved real log remains absent.
