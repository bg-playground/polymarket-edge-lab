from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

DEFAULT_EVENT_COUNT = 70_000
DEFAULT_SAMPLE_WINDOW = 500
DEFAULT_MAX_GROWTH_RATIO = 5.0
DEFAULT_MAX_LATE_MEDIAN_MS = 50.0


@dataclass(frozen=True)
class EndurancePreflightReport:
    schema_version: str
    ready: bool
    event_log: str
    requested_event_count: int
    final_event_count: int
    file_size_bytes: int
    early_median_append_ms: float
    late_median_append_ms: float
    late_to_early_median_ratio: float
    restart_scan_seconds: float
    restart_next_sequence: int
    continuity_append_sequence: int
    max_growth_ratio: float
    max_late_median_ms: float
    alerts: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _synthetic_event(run_id: str, sequence: int, created_at: datetime) -> EventEnvelope:
    return EventEnvelope(
        schema_version="m4a-event-v1",
        event_type="source_health",
        event_id=f"{run_id}:{sequence}",
        run_id=run_id,
        sequence=sequence,
        created_at=created_at,
        payload={
            "source": "m4a-endurance-preflight",
            "status": "synthetic",
            "detail": "disposable persistence throughput probe",
            "raw_observation_event_id": None,
        },
    )


def run_event_store_endurance_preflight(
    event_log: Path,
    *,
    event_count: int = DEFAULT_EVENT_COUNT,
    sample_window: int = DEFAULT_SAMPLE_WINDOW,
    max_growth_ratio: float = DEFAULT_MAX_GROWTH_RATIO,
    max_late_median_ms: float = DEFAULT_MAX_LATE_MEDIAN_MS,
    run_id: str = "m4a-endurance-disposable",
) -> EndurancePreflightReport:
    if event_count < 2:
        raise ValueError("event_count must be at least 2")
    if sample_window < 1 or sample_window * 2 > event_count:
        raise ValueError("sample_window must fit twice within event_count")
    if max_growth_ratio <= 0:
        raise ValueError("max_growth_ratio must be positive")
    if max_late_median_ms <= 0:
        raise ValueError("max_late_median_ms must be positive")
    if event_log.exists():
        raise FileExistsError(f"endurance event log already exists: {event_log}")

    event_log.parent.mkdir(parents=True, exist_ok=True)
    store = AppendOnlyEventStore(event_log)
    base_time = datetime.now(tz=UTC)
    early_latencies: list[float] = []
    late_latencies: list[float] = []

    for sequence in range(event_count):
        event = _synthetic_event(
            run_id,
            sequence,
            base_time + timedelta(microseconds=sequence),
        )
        started = time.perf_counter()
        store.append(event)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if sequence < sample_window:
            early_latencies.append(elapsed_ms)
        if sequence >= event_count - sample_window:
            late_latencies.append(elapsed_ms)

    early_median = statistics.median(early_latencies)
    late_median = statistics.median(late_latencies)
    growth_ratio = late_median / early_median if early_median > 0 else float("inf")

    restart_started = time.perf_counter()
    restarted = AppendOnlyEventStore(event_log)
    restart_scan_seconds = time.perf_counter() - restart_started
    restart_next_sequence = restarted.next_sequence()

    continuity_sequence = restart_next_sequence
    restarted.append(
        _synthetic_event(
            run_id,
            continuity_sequence,
            base_time + timedelta(microseconds=event_count),
        )
    )

    alerts: list[str] = []
    if restart_next_sequence != event_count:
        alerts.append(f"restart next sequence {restart_next_sequence} != expected {event_count}")
    if growth_ratio > max_growth_ratio:
        alerts.append(
            f"late/early median append ratio {growth_ratio:.3f} exceeds {max_growth_ratio:.3f}"
        )
    if late_median > max_late_median_ms:
        alerts.append(
            f"late median append latency {late_median:.3f} ms exceeds {max_late_median_ms:.3f} ms"
        )

    return EndurancePreflightReport(
        schema_version="m4a-endurance-preflight-v1",
        ready=not alerts,
        event_log=str(event_log),
        requested_event_count=event_count,
        final_event_count=continuity_sequence + 1,
        file_size_bytes=event_log.stat().st_size,
        early_median_append_ms=early_median,
        late_median_append_ms=late_median,
        late_to_early_median_ratio=growth_ratio,
        restart_scan_seconds=restart_scan_seconds,
        restart_next_sequence=restart_next_sequence,
        continuity_append_sequence=continuity_sequence,
        max_growth_ratio=max_growth_ratio,
        max_late_median_ms=max_late_median_ms,
        alerts=tuple(alerts),
    )
