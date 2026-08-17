from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from polymarket_edge_lab.shadow.binding import ProspectiveOutcomeBinder
from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.feature_cadence import active_market_ids
from polymarket_edge_lab.shadow.state_processor import LiveStateProcessor
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

SCHEMA_VERSION = "m4a-runtime-endurance-preflight-v1"
DEFAULT_EVENT_COUNT = 100_000
DEFAULT_CYCLE_COUNT = 100
DEFAULT_MAX_P95_CYCLE_MS = 250.0
DEFAULT_MAX_CYCLE_MS = 1000.0
RUN_ID = "m4a-runtime-endurance-disposable"
BASE_TIME = datetime(2026, 8, 17, 11, 0, tzinfo=UTC)


@dataclass(frozen=True)
class RuntimeEnduranceReport:
    schema_version: str
    event_log: str
    seeded_event_count: int
    cycle_count: int
    final_event_count: int
    seed_seconds: float
    restart_scan_seconds: float
    processor_restore_seconds: float
    median_cycle_ms: float
    p95_cycle_ms: float
    max_cycle_ms: float
    max_p95_cycle_ms: float
    max_allowed_cycle_ms: float
    ready: bool
    alerts: list[str]


def _seed_record(sequence: int) -> dict[str, object]:
    return {
        "schema_version": "m4a-event-v1",
        "event_type": "source_health",
        "event_id": f"{RUN_ID}:{sequence}",
        "run_id": RUN_ID,
        "sequence": sequence,
        "created_at": BASE_TIME.isoformat(),
        "payload": {
            "source": "synthetic-endurance",
            "status": "poll_ok",
            "detail": "seed",
            "raw_observation_event_id": None,
        },
        "supersedes_event_id": None,
    }


def _seed_log(path: Path, event_count: int) -> float:
    if path.exists():
        raise ValueError(f"refusing existing endurance event log: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for sequence in range(event_count):
            line = json.dumps(
                _seed_record(sequence), sort_keys=True, separators=(",", ":")
            )
            handle.write(line + "\n")
        handle.flush()
    return time.perf_counter() - started


def _append_heartbeat(store: AppendOnlyEventStore, cycle: int) -> None:
    sequence = store.next_sequence()
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type="source_health",
            event_id=f"{RUN_ID}:{sequence}",
            run_id=RUN_ID,
            sequence=sequence,
            created_at=BASE_TIME,
            payload={
                "source": "synthetic-endurance",
                "status": "poll_ok",
                "detail": f"cycle={cycle}",
                "raw_observation_event_id": None,
            },
        )
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def run_runtime_endurance_preflight(
    *,
    event_log: Path,
    event_count: int = DEFAULT_EVENT_COUNT,
    cycle_count: int = DEFAULT_CYCLE_COUNT,
    max_p95_cycle_ms: float = DEFAULT_MAX_P95_CYCLE_MS,
    max_cycle_ms: float = DEFAULT_MAX_CYCLE_MS,
) -> RuntimeEnduranceReport:
    if event_count <= 0:
        raise ValueError("event_count must be positive")
    if cycle_count <= 0:
        raise ValueError("cycle_count must be positive")
    if max_p95_cycle_ms <= 0 or max_cycle_ms <= 0:
        raise ValueError("runtime endurance thresholds must be positive")

    seed_seconds = _seed_log(event_log, event_count)
    started = time.perf_counter()
    store = AppendOnlyEventStore(event_log)
    restart_scan_seconds = time.perf_counter() - started

    started = time.perf_counter()
    processor = LiveStateProcessor(run_id=RUN_ID, store=store)
    binder = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store)
    processor_restore_seconds = time.perf_counter() - started

    cycle_ms: list[float] = []
    for cycle in range(cycle_count):
        _append_heartbeat(store, cycle)
        started = time.perf_counter()
        processor.process_pending()
        binder.process_pending()
        active_market_ids(
            store,
            tick_time=BASE_TIME,
            as_of_sequence=store.next_sequence() - 1,
        )
        cycle_ms.append((time.perf_counter() - started) * 1000.0)

    median_cycle_ms = statistics.median(cycle_ms)
    p95_cycle_ms = _percentile(cycle_ms, 0.95)
    observed_max_cycle_ms = max(cycle_ms)
    alerts: list[str] = []
    if p95_cycle_ms > max_p95_cycle_ms:
        alerts.append(
            f"p95 processing cycle {p95_cycle_ms:.3f} ms exceeds "
            f"{max_p95_cycle_ms:.3f} ms"
        )
    if observed_max_cycle_ms > max_cycle_ms:
        alerts.append(
            f"maximum processing cycle {observed_max_cycle_ms:.3f} ms exceeds "
            f"{max_cycle_ms:.3f} ms"
        )

    return RuntimeEnduranceReport(
        schema_version=SCHEMA_VERSION,
        event_log=str(event_log),
        seeded_event_count=event_count,
        cycle_count=cycle_count,
        final_event_count=store.next_sequence(),
        seed_seconds=seed_seconds,
        restart_scan_seconds=restart_scan_seconds,
        processor_restore_seconds=processor_restore_seconds,
        median_cycle_ms=median_cycle_ms,
        p95_cycle_ms=p95_cycle_ms,
        max_cycle_ms=observed_max_cycle_ms,
        max_p95_cycle_ms=max_p95_cycle_ms,
        max_allowed_cycle_ms=max_cycle_ms,
        ready=not alerts,
        alerts=alerts,
    )


def json_dumps(report: RuntimeEnduranceReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True)
