from pathlib import Path

import pytest

from polymarket_edge_lab.shadow import store as store_module
from polymarket_edge_lab.shadow.endurance_preflight import run_event_store_endurance_preflight


def test_endurance_preflight_validates_growth_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module.os, "fsync", lambda _fd: None)
    event_log = tmp_path / "endurance.ndjson"

    report = run_event_store_endurance_preflight(
        event_log,
        event_count=200,
        sample_window=20,
        max_growth_ratio=20.0,
        max_late_median_ms=100.0,
    )

    assert report.ready is True
    assert report.requested_event_count == 200
    assert report.restart_next_sequence == 200
    assert report.continuity_append_sequence == 200
    assert report.final_event_count == 201
    assert report.file_size_bytes > 0
    assert report.alerts == ()


def test_endurance_preflight_refuses_existing_log(tmp_path: Path) -> None:
    event_log = tmp_path / "endurance.ndjson"
    event_log.write_text("reserved\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        run_event_store_endurance_preflight(event_log, event_count=20, sample_window=5)


def test_endurance_preflight_fails_closed_on_latency_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module.os, "fsync", lambda _fd: None)
    event_log = tmp_path / "endurance.ndjson"

    report = run_event_store_endurance_preflight(
        event_log,
        event_count=40,
        sample_window=10,
        max_growth_ratio=1000.0,
        max_late_median_ms=0.000001,
    )

    assert report.ready is False
    assert any("late median append latency" in alert for alert in report.alerts)


def test_endurance_preflight_validates_arguments(tmp_path: Path) -> None:
    event_log = tmp_path / "endurance.ndjson"

    with pytest.raises(ValueError, match="event_count"):
        run_event_store_endurance_preflight(event_log, event_count=1)
    with pytest.raises(ValueError, match="sample_window"):
        run_event_store_endurance_preflight(event_log, event_count=10, sample_window=6)
    with pytest.raises(ValueError, match="max_growth_ratio"):
        run_event_store_endurance_preflight(
            event_log,
            event_count=10,
            sample_window=5,
            max_growth_ratio=0.0,
        )
    with pytest.raises(ValueError, match="max_late_median_ms"):
        run_event_store_endurance_preflight(
            event_log,
            event_count=10,
            sample_window=5,
            max_late_median_ms=0.0,
        )
