# Project State Before Milestone 4A Second Frozen Evaluation

## Status

The first frozen prospective launch, `m4a-frozen-20260815`, is sealed as an operationally failed launch and must not be resumed or modified. It exposed event-store persistence work that scaled with total log size and starved source polling under live volume.

PR #33 removed the steady-state full-log rescan from every append while preserving one full continuity validation at store open/restart, durable flush and `fsync`, exact monotonic sequence semantics, and fail-closed single-writer detection.

PR #34 adds a disposable high-volume endurance preflight. The second real frozen evaluation must not be launched until the 70,000-event endurance gate passes on the intended Windows host and the resulting JSON report has been reviewed.

## Frozen semantic contract

The second launch must preserve the same target-account, source, market eligibility, fill admission, FIFO pairing, Stage 3G feature/model, stale-source, 12:00–18:00 UTC window, score-binding, advancement, and read-only/shadow-only semantics used by the first launch. Persistence throughput hardening does not authorize any semantic change.

## Relaunch requirements

After the endurance gate passes:

1. preserve the endurance JSON report outside any real evaluation log;
2. choose a fresh run ID;
3. reserve a fresh evaluation-log path that does not exist;
4. pin the repository commit that contains the merged PR #33 and PR #34 changes;
5. run the formal frozen-evaluation preflight against the same frozen Stage 3G artifacts;
6. verify the reserved evaluation log still does not exist after preflight;
7. only then launch the second frozen prospective evaluation from sequence zero.

This document is a handoff boundary only. It does not declare the second launch ready until the host endurance report and formal frozen preflight both pass.
