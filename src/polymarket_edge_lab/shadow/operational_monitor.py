from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

HealthStatus = Literal["HEALTHY", "DEGRADED", "CRITICAL"]

_SCHEMA_VERSION = "m4a-frozen-operational-monitor-v1"
_RECENT_WINDOW = timedelta(minutes=5)
_GAP_WINDOW = timedelta(minutes=15)


@dataclass(frozen=True)
class SourceHealthSnapshot:
    source: str
    last_status: str | None
    last_detail: str | None
    last_event_at: str | None
    last_ok_at: str | None
    last_ok_age_seconds: float | None
    recent_non_ok_count: int


@dataclass(frozen=True)
class IntegritySnapshot:
    malformed_line_count: int
    partial_tail_line_count: int
    sequence_error_count: int
    event_id_error_count: int
    evaluation_start_count: int
    sequence_zero_valid: bool


@dataclass(frozen=True)
class OperationalMonitorReport:
    schema_version: str
    generated_at: str
    status: HealthStatus
    event_log: str
    run_id: str | None
    repository_commit: str | None
    evaluation_started_at: str | None
    latest_sequence: int | None
    latest_event_at: str | None
    latest_event_age_seconds: float | None
    event_count: int
    event_counts: dict[str, int]
    binding_status_counts: dict[str, int]
    source_health: dict[str, SourceHealthSnapshot]
    integrity: IntegritySnapshot
    advancement_window: dict[str, object]
    recent_max_event_gap_seconds: float | None
    alerts: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _as_dict(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _age_seconds(now: datetime, at: datetime | None) -> float | None:
    if at is None:
        return None
    return max(0.0, (now - at).total_seconds())


def _window_snapshot(
    *,
    now: datetime,
    started_at: datetime | None,
    start_payload: dict[str, object] | None,
) -> dict[str, object]:
    start_hour = 12
    end_hour = 18
    if start_payload is not None:
        try:
            start_hour = int(str(start_payload.get("evaluation_start_hour_utc", start_hour)))
            end_hour = int(str(start_payload.get("evaluation_end_hour_utc", end_hour)))
        except ValueError:
            pass
    in_window = start_hour <= now.hour < end_hour
    elapsed_days = None
    if started_at is not None:
        elapsed_days = (now.date() - started_at.date()).days + 1
    return {
        "start_hour_utc": start_hour,
        "end_hour_utc": end_hour,
        "in_window": in_window,
        "elapsed_calendar_days": elapsed_days,
        "current_utc_date": now.date().isoformat(),
    }


def inspect_frozen_evaluation_log(
    event_log: Path, *, now: datetime | None = None
) -> OperationalMonitorReport:
    """Inspect an active frozen-evaluation NDJSON log without opening it for writes."""
    observed_now = (now or _utc_now()).astimezone(UTC)
    alerts: list[str] = []
    event_counts: Counter[str] = Counter()
    binding_counts: Counter[str] = Counter()
    source_last: dict[str, tuple[datetime, str, str | None]] = {}
    source_last_ok: dict[str, datetime] = {}
    source_recent_non_ok: Counter[str] = Counter()

    malformed_line_count = 0
    partial_tail_line_count = 0
    sequence_error_count = 0
    event_id_error_count = 0
    evaluation_start_count = 0
    sequence_zero_valid = False
    event_count = 0
    expected_sequence = 0
    latest_sequence: int | None = None
    latest_event_at: datetime | None = None
    prior_recent_event_at: datetime | None = None
    recent_max_gap: float | None = None
    run_id: str | None = None
    repository_commit: str | None = None
    evaluation_started_at: datetime | None = None
    start_payload: dict[str, object] | None = None

    if not event_log.exists() or not event_log.is_file():
        alerts.append("event log is missing or not a regular file")
        integrity = IntegritySnapshot(0, 0, 0, 0, 0, False)
        return OperationalMonitorReport(
            schema_version=_SCHEMA_VERSION,
            generated_at=observed_now.isoformat(),
            status="CRITICAL",
            event_log=str(event_log),
            run_id=None,
            repository_commit=None,
            evaluation_started_at=None,
            latest_sequence=None,
            latest_event_at=None,
            latest_event_age_seconds=None,
            event_count=0,
            event_counts={},
            binding_status_counts={},
            source_health={},
            integrity=integrity,
            advancement_window=_window_snapshot(
                now=observed_now, started_at=None, start_payload=None
            ),
            recent_max_event_gap_seconds=None,
            alerts=alerts,
        )

    with event_log.open("r", encoding="utf-8", newline="") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                if not raw_line.endswith(("\n", "\r")):
                    partial_tail_line_count += 1
                    break
                malformed_line_count += 1
                alerts.append(f"malformed NDJSON at line {line_number}")
                continue
            if not isinstance(record, dict):
                malformed_line_count += 1
                alerts.append(f"non-object NDJSON record at line {line_number}")
                continue

            event_count += 1
            event_type = str(record.get("event_type") or "unknown")
            event_counts[event_type] += 1
            record_run_id = str(record.get("run_id") or "")
            if run_id is None and record_run_id:
                run_id = record_run_id

            try:
                sequence = int(str(record["sequence"]))
            except (KeyError, ValueError):
                sequence_error_count += 1
                alerts.append(f"invalid sequence at line {line_number}")
                continue
            if sequence != expected_sequence:
                sequence_error_count += 1
                alerts.append(
                    f"sequence discontinuity at line {line_number}: "
                    f"expected {expected_sequence}, found {sequence}"
                )
                expected_sequence = sequence + 1
            else:
                expected_sequence += 1
            latest_sequence = sequence

            event_id = str(record.get("event_id") or "")
            if record_run_id and event_id != f"{record_run_id}:{sequence}":
                event_id_error_count += 1
                alerts.append(f"event_id mismatch at sequence {sequence}")

            created_at = _parse_datetime(record.get("created_at"))
            if created_at is None:
                alerts.append(f"invalid created_at at sequence {sequence}")
            else:
                if latest_event_at is None or created_at > latest_event_at:
                    latest_event_at = created_at
                if created_at >= observed_now - _GAP_WINDOW:
                    if prior_recent_event_at is not None and created_at >= prior_recent_event_at:
                        gap = (created_at - prior_recent_event_at).total_seconds()
                        recent_max_gap = gap if recent_max_gap is None else max(recent_max_gap, gap)
                    prior_recent_event_at = created_at

            payload = _as_dict(record.get("payload"))
            if event_type == "evaluation_run_start":
                evaluation_start_count += 1
                if sequence == 0 and payload is not None:
                    evaluation_started_at = created_at
                    start_payload = payload
                    repository_commit = str(payload.get("repository_commit") or "") or None
                    sequence_zero_valid = (
                        bool(payload.get("frozen_evaluation"))
                        and record_run_id == run_id
                        and event_id == f"{record_run_id}:0"
                    )

            if event_type == "score_binding" and payload is not None:
                binding_counts[str(payload.get("status") or "unknown")] += 1

            if event_type == "source_health" and payload is not None and created_at is not None:
                source = str(payload.get("source") or "unknown")
                status = str(payload.get("status") or "unknown")
                detail_value = payload.get("detail")
                detail = str(detail_value) if detail_value is not None else None
                source_last[source] = (created_at, status, detail)
                if status == "poll_ok":
                    source_last_ok[source] = created_at
                elif created_at >= observed_now - _RECENT_WINDOW:
                    source_recent_non_ok[source] += 1

    if partial_tail_line_count:
        alerts.append("active log ended with a partial tail line; retry monitor after next append")

    source_snapshots: dict[str, SourceHealthSnapshot] = {}
    for source in sorted(set(source_last) | set(source_last_ok)):
        last = source_last.get(source)
        last_ok = source_last_ok.get(source)
        source_snapshots[source] = SourceHealthSnapshot(
            source=source,
            last_status=last[1] if last is not None else None,
            last_detail=last[2] if last is not None else None,
            last_event_at=last[0].isoformat() if last is not None else None,
            last_ok_at=last_ok.isoformat() if last_ok is not None else None,
            last_ok_age_seconds=_age_seconds(observed_now, last_ok),
            recent_non_ok_count=source_recent_non_ok[source],
        )

    integrity = IntegritySnapshot(
        malformed_line_count=malformed_line_count,
        partial_tail_line_count=partial_tail_line_count,
        sequence_error_count=sequence_error_count,
        event_id_error_count=event_id_error_count,
        evaluation_start_count=evaluation_start_count,
        sequence_zero_valid=sequence_zero_valid,
    )

    critical = False
    degraded = False
    if malformed_line_count or sequence_error_count or event_id_error_count:
        critical = True
    if evaluation_start_count != 1 or not sequence_zero_valid:
        alerts.append("frozen evaluation must contain exactly one valid sequence-zero start record")
        critical = True

    latest_age = _age_seconds(observed_now, latest_event_at)
    if latest_age is None or latest_age > 60:
        alerts.append("latest durable event is more than 60 seconds old")
        critical = True
    elif latest_age > 10:
        alerts.append("latest durable event is more than 10 seconds old")
        degraded = True

    freshness_limits = {
        "polymarket-data-api": (10.0, 60.0),
        "coinbase-exchange-rest": (20.0, 60.0),
    }
    for source, (degraded_after, critical_after) in freshness_limits.items():
        snapshot = source_snapshots.get(source)
        age = snapshot.last_ok_age_seconds if snapshot is not None else None
        if age is None or age > critical_after:
            alerts.append(
                f"{source} has no successful poll in the last "
                f"{critical_after:.0f} seconds"
            )
            critical = True
        elif age > degraded_after:
            alerts.append(f"{source} successful poll is {age:.1f} seconds old")
            degraded = True
        if snapshot is not None and snapshot.recent_non_ok_count:
            alerts.append(
                f"{source} has {snapshot.recent_non_ok_count} non-ok health event(s) "
                "in the last 5 minutes"
            )
            degraded = True

    if event_counts["state_quarantine"]:
        alerts.append(f"{event_counts['state_quarantine']} state quarantine event(s) recorded")
        degraded = True
    if partial_tail_line_count:
        degraded = True
    if recent_max_gap is not None:
        if recent_max_gap > 60:
            alerts.append(f"recent durable event gap reached {recent_max_gap:.1f} seconds")
            critical = True
        elif recent_max_gap > 15:
            alerts.append(f"recent durable event gap reached {recent_max_gap:.1f} seconds")
            degraded = True

    status: HealthStatus = "CRITICAL" if critical else "DEGRADED" if degraded else "HEALTHY"
    evaluation_started_at_text = (
        evaluation_started_at.isoformat() if evaluation_started_at else None
    )
    latest_event_at_text = latest_event_at.isoformat() if latest_event_at else None
    return OperationalMonitorReport(
        schema_version=_SCHEMA_VERSION,
        generated_at=observed_now.isoformat(),
        status=status,
        event_log=str(event_log),
        run_id=run_id,
        repository_commit=repository_commit,
        evaluation_started_at=evaluation_started_at_text,
        latest_sequence=latest_sequence,
        latest_event_at=latest_event_at_text,
        latest_event_age_seconds=latest_age,
        event_count=event_count,
        event_counts=dict(sorted(event_counts.items())),
        binding_status_counts=dict(sorted(binding_counts.items())),
        source_health=source_snapshots,
        integrity=integrity,
        advancement_window=_window_snapshot(
            now=observed_now,
            started_at=evaluation_started_at,
            start_payload=start_payload,
        ),
        recent_max_event_gap_seconds=recent_max_gap,
        alerts=alerts,
    )


def render_operational_summary(report: OperationalMonitorReport) -> str:
    """Render a compact human-readable operational snapshot."""
    counts = report.event_counts
    latest_sequence = report.latest_sequence if report.latest_sequence is not None else "unknown"
    lines = [
        f"M4A frozen evaluation: {report.status}",
        f"run_id: {report.run_id or 'unknown'}",
        f"repository_commit: {report.repository_commit or 'unknown'}",
        f"latest_sequence: {latest_sequence}",
        f"latest_event_age_seconds: "
        f"{report.latest_event_age_seconds:.1f}"
        if report.latest_event_age_seconds is not None
        else "latest_event_age_seconds: unknown",
        (
            "counts: "
            f"fills={counts.get('normalized_fill', 0)} "
            f"features={counts.get('feature_snapshot', 0)} "
            f"predictions={counts.get('prediction', 0)} "
            f"pairs={counts.get('pair_formation', 0)} "
            f"outcomes={counts.get('outcome_label', 0)} "
            f"bindings={counts.get('score_binding', 0)} "
            f"quarantines={counts.get('state_quarantine', 0)}"
        ),
    ]
    for source, snapshot in sorted(report.source_health.items()):
        age = (
            f"{snapshot.last_ok_age_seconds:.1f}s"
            if snapshot.last_ok_age_seconds is not None
            else "never"
        )
        lines.append(
            f"source {source}: last_status={snapshot.last_status or 'unknown'} "
            f"last_ok_age={age} recent_non_ok={snapshot.recent_non_ok_count}"
        )
    window = report.advancement_window
    lines.append(
        "advancement_window: "
        f"{window['start_hour_utc']:02d}:00-{window['end_hour_utc']:02d}:00 UTC "
        f"in_window={str(window['in_window']).lower()} "
        f"elapsed_calendar_days={window['elapsed_calendar_days']}"
    )
    if report.alerts:
        lines.append("alerts:")
        lines.extend(f"- {alert}" for alert in report.alerts)
    else:
        lines.append("alerts: none")
    return "\n".join(lines)
