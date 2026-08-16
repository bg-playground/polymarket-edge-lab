# Milestone 4A Frozen Evaluation Operational Monitor

## Purpose

This monitor observes the active Milestone 4A frozen prospective evaluation without changing it.
It is deliberately outside the frozen engine write path: it reads the NDJSON event log directly,
never instantiates `AppendOnlyEventStore`, makes no external API calls, and does not alter model,
feature, FIFO, stale-data, binding, reporting, or advancement semantics.

Monitoring output is operational only. `HEALTHY`, `DEGRADED`, and `CRITICAL` describe collection and
durable-log health; they do not indicate whether the trading hypothesis is succeeding.

## Safety boundary

The monitor:

- opens the frozen event log read-only;
- never appends, repairs, truncates, backfills, or rewrites evaluation records;
- tolerates one unterminated partial final line as a transient active-write condition;
- makes no Polymarket, Coinbase, Gamma, or other network request;
- does not call the live runner, collector, scorer, binder, reporting, or replay code;
- can optionally write a separate JSON snapshot, but refuses to use the event-log path as output.

Develop and test the monitor only against fixtures or copies. The merged monitor may then inspect the
real log because its implementation is read-only.

## Status classification

`CRITICAL` is reserved for conditions such as malformed durable NDJSON, sequence/event-ID damage,
missing or duplicated sequence-zero frozen start, latest durable activity older than 60 seconds,
Polymarket/Coinbase successful polling older than 60 seconds, or a recent durable event gap longer
than 60 seconds.

`DEGRADED` covers softer operational warnings such as modest staleness, recent transient source-health
failures, a durable state quarantine, a 15–60 second recent event gap, or observing an unterminated
partial tail line while the collector is appending.

`HEALTHY` means none of those operational conditions are present.

The freshness expectations reflect the already frozen live cadences: approximately 1-second target
polling and 5-second Coinbase polling. They are monitoring thresholds only and do not change the
underlying collection cadence or evaluation inclusion rules.

## Human-readable snapshot

From the repository checkout containing the merged monitor:

```powershell
$EVENT_LOG = "C:\Users\bradg\OneDrive\Documents\GitHub\Artifacts\PolymarketEdgeLab\m4a-frozen-20260815\m4a-frozen-evaluation.ndjson"

python scripts/monitor_m4a_frozen_evaluation.py --event-log $EVENT_LOG
```

The summary includes run identity, repository commit, latest sequence/event age, durable counts for
fills/features/predictions/pairs/outcomes/bindings/quarantines, source-health freshness, frozen
advancement-window status, and any operational alerts.

## Machine-readable snapshot

```powershell
$MONITOR_DIR = "C:\Users\bradg\OneDrive\Documents\GitHub\Artifacts\PolymarketEdgeLab\m4a-frozen-20260815\monitor"
$MONITOR_REPORT = "$MONITOR_DIR\health.json"

python scripts/monitor_m4a_frozen_evaluation.py `
  --event-log $EVENT_LOG `
  --json `
  --output $MONITOR_REPORT
```

The JSON output uses schema `m4a-frozen-operational-monitor-v1`. The separate output path is not part
of the prospective evaluation dataset and must never be set to the evaluation log itself.

## Interpretation during the frozen window

The monitor may display zero fills, predictions, pairs, outcomes, or bindings for quiet periods. That
is not itself a health failure. Operational health is based on durable append activity, source-health
cadence, structural integrity, and explicit quarantine/failure records.

The frozen 12:00–18:00 UTC advancement window is reported for operator context only. The monitor does
not compute or modify advancement criteria and must not be used as a substitute for the frozen
prospective report or bounded replay audit.
