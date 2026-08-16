# Milestone 4A Live Throughput Hardening

## Incident summary

The first frozen live launch (`m4a-frozen-20260815`) is preserved as an operationally failed launch. The run remained read-only and fail-closed, but source polling became increasingly stale as the event log grew. During the first 12:00-18:00 UTC window, the scorer emitted `target_source_stale` rather than producing predictions from stale target-account state.

The failed run must not be repaired, truncated, backfilled, or reused after this change. A subsequent prospective launch requires a new run ID and a new sequence-zero event log while retaining the already frozen model, feature, stale-data, evaluation-window, FIFO, and binding semantics.

## Root cause

`AppendOnlyEventStore.append()` previously called `next_sequence()` for every event. `next_sequence()` reparsed the complete NDJSON log from sequence zero to validate continuity. With tens of thousands of durable events, every append therefore performed work proportional to the entire accumulated log. The live engine appends many events for each source response, fill, state application, pair, outcome, binding, and tick, making steady-state persistence effectively quadratic in total event count.

This explains the observed pattern of sustained CPU saturation, long periods without fresh source polls, and successful HTTP responses whose recorded request durations stretched into minutes even when direct endpoint probes from the host completed in under a second.

## Bounded fix

The event store now performs the full continuity scan once when an `AppendOnlyEventStore` instance opens. It caches the next sequence and durable file size for the lifetime of that single writer. Each append remains flushed and `fsync`-durable, advances the cached sequence only after the durable write completes, and verifies that the file size has not changed outside the store instance before returning or appending.

This removes repeated full-log reparsing from the steady-state append path without changing event schemas, ordering rules, sequence numbering, append durability, or any model/evaluation semantics.

An independently opened stale writer fails closed if another writer changes the file. Restart still performs a complete continuity validation before resuming from the existing next sequence.

## Frozen-contract boundary

This PR does not change:

- target account or source APIs;
- target, BTC, or feature cadences;
- market eligibility or metadata classification;
- normalized-fill admission semantics;
- FIFO state or pair formation;
- Stage 3G feature construction or frozen model artifacts;
- stale-source thresholds;
- the 12:00-18:00 UTC evaluation window;
- prediction/outcome binding or advancement semantics;
- read-only/shadow-only behavior.

The change is operational persistence hardening only.

## Validation and relaunch

Regression tests require steady-state `next_sequence()` and `append()` to operate without calling `iter_records()`, verify restart continuation from an existing log, preserve contiguous event order, and fail closed when a second store instance observes an external append.

After merge, rerun the full frozen preflight against the same frozen model artifacts but reserve a brand-new evaluation-log path and run ID. Do not resume `m4a-frozen-20260815` with the hardened store.
