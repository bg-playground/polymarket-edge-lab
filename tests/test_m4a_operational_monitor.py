from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_edge_lab.shadow.operational_monitor import (
    inspect_frozen_evaluation_log,
    render_operational_summary,
)

RUN_ID = "m4a-frozen-test"
COMMIT = "4" * 40
START = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)


def _record(
    sequence: int,
    event_type: str,
    created_at: datetime,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "m4a-event-v1",
        "event_type": event_type,
        "event_id": f"{RUN_ID}:{sequence}",
        "run_id": RUN_ID,
        "sequence": sequence,
        "created_at": created_at.isoformat(),
        "payload": payload,
        "supersedes_event_id": None,
    }


def _healthy_records(now: datetime) -> list[dict[str, object]]:
    return [
        _record(
            0,
            "evaluation_run_start",
            now - timedelta(hours=1),
            {
                "frozen_evaluation": True,
                "repository_commit": COMMIT,
                "evaluation_start_hour_utc": 12,
                "evaluation_end_hour_utc": 18,
            },
        ),
        _record(1, "normalized_fill", now - timedelta(seconds=5), {"market_id": "market"}),
        _record(2, "feature_snapshot", now - timedelta(seconds=4), {"market_id": "market"}),
        _record(3, "prediction", now - timedelta(seconds=3), {"market_id": "market"}),
        _record(4, "pair_formation", now - timedelta(seconds=2), {"market_id": "market"}),
        _record(5, "outcome_label", now - timedelta(seconds=2), {"market_id": "market"}),
        _record(
            6,
            "score_binding",
            now - timedelta(seconds=2),
            {"status": "bound_strictly_prior_score"},
        ),
        _record(
            7,
            "source_health",
            now - timedelta(seconds=1),
            {"source": "coinbase-exchange-rest", "status": "poll_ok", "detail": "ok"},
        ),
        _record(
            8,
            "source_health",
            now - timedelta(milliseconds=500),
            {"source": "polymarket-data-api", "status": "poll_ok", "detail": "ok"},
        ),
    ]


def _write(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def test_monitor_is_read_only_and_reports_healthy_fixture(tmp_path: Path) -> None:
    now = START + timedelta(hours=12, minutes=30)
    event_log = tmp_path / "events.ndjson"
    _write(event_log, _healthy_records(now))
    before = event_log.read_bytes()

    report = inspect_frozen_evaluation_log(event_log, now=now)

    assert event_log.read_bytes() == before
    assert report.status == "HEALTHY"
    assert report.run_id == RUN_ID
    assert report.repository_commit == COMMIT
    assert report.latest_sequence == 8
    assert report.integrity.evaluation_start_count == 1
    assert report.integrity.sequence_zero_valid is True
    assert report.event_counts["normalized_fill"] == 1
    assert report.event_counts["prediction"] == 1
    assert report.binding_status_counts["bound_strictly_prior_score"] == 1
    assert report.advancement_window["in_window"] is True
    assert report.source_health["polymarket-data-api"].last_status == "poll_ok"
    assert report.source_health["coinbase-exchange-rest"].last_status == "poll_ok"
    assert report.alerts == []
    rendered = render_operational_summary(report)
    assert "M4A frozen evaluation: HEALTHY" in rendered
    assert "predictions=1" in rendered


def test_monitor_degrades_on_transient_partial_tail_without_mutation(tmp_path: Path) -> None:
    now = START + timedelta(minutes=10)
    event_log = tmp_path / "events.ndjson"
    _write(event_log, _healthy_records(now))
    with event_log.open("ab") as handle:
        handle.write(b'{"event_type":"raw_observation"')
    before = event_log.read_bytes()

    report = inspect_frozen_evaluation_log(event_log, now=now)

    assert event_log.read_bytes() == before
    assert report.status == "DEGRADED"
    assert report.integrity.partial_tail_line_count == 1
    assert report.integrity.malformed_line_count == 0
    assert any("partial tail line" in alert for alert in report.alerts)


def test_monitor_marks_sequence_and_start_contract_damage_critical(tmp_path: Path) -> None:
    now = START + timedelta(minutes=10)
    records = _healthy_records(now)
    records[0]["event_type"] = "source_health"
    records[4]["sequence"] = 99
    event_log = tmp_path / "events.ndjson"
    _write(event_log, records)

    report = inspect_frozen_evaluation_log(event_log, now=now)

    assert report.status == "CRITICAL"
    assert report.integrity.sequence_error_count >= 1
    assert report.integrity.evaluation_start_count == 0
    assert report.integrity.sequence_zero_valid is False
    assert any("exactly one valid sequence-zero" in alert for alert in report.alerts)


def test_monitor_marks_stale_sources_critical(tmp_path: Path) -> None:
    baseline = START + timedelta(minutes=10)
    event_log = tmp_path / "events.ndjson"
    _write(event_log, _healthy_records(baseline))

    report = inspect_frozen_evaluation_log(event_log, now=baseline + timedelta(minutes=2))

    assert report.status == "CRITICAL"
    assert report.latest_event_age_seconds is not None
    assert report.latest_event_age_seconds > 60
    assert any("polymarket-data-api" in alert for alert in report.alerts)
    assert any("coinbase-exchange-rest" in alert for alert in report.alerts)


def test_monitor_surfaces_non_ok_source_health_and_quarantine(tmp_path: Path) -> None:
    now = START + timedelta(minutes=10)
    records = _healthy_records(now)
    records.extend(
        [
            _record(
                9,
                "source_health",
                now - timedelta(milliseconds=300),
                {
                    "source": "polymarket-data-api",
                    "status": "transport_failed",
                    "detail": "temporary",
                },
            ),
            _record(10, "state_quarantine", now - timedelta(milliseconds=200), {"reason": "x"}),
            _record(
                11,
                "source_health",
                now - timedelta(milliseconds=100),
                {"source": "polymarket-data-api", "status": "poll_ok", "detail": "recovered"},
            ),
        ]
    )
    event_log = tmp_path / "events.ndjson"
    _write(event_log, records)

    report = inspect_frozen_evaluation_log(event_log, now=now)

    assert report.status == "DEGRADED"
    assert report.source_health["polymarket-data-api"].recent_non_ok_count == 1
    assert report.event_counts["state_quarantine"] == 1
    assert any("quarantine" in alert for alert in report.alerts)
