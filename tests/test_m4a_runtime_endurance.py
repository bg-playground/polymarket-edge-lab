from __future__ import annotations

from pathlib import Path

import pytest

from polymarket_edge_lab.shadow.runtime_endurance import run_runtime_endurance_preflight


def test_runtime_endurance_passes_on_disposable_large_log(tmp_path: Path) -> None:
    path = tmp_path / "runtime-endurance.ndjson"

    report = run_runtime_endurance_preflight(
        event_log=path,
        event_count=2_000,
        cycle_count=5,
        max_p95_cycle_ms=2_000.0,
        max_cycle_ms=5_000.0,
    )

    assert report.ready is True
    assert report.alerts == []
    assert report.seeded_event_count == 2_000
    assert report.final_event_count == 2_005


def test_runtime_endurance_refuses_existing_log(tmp_path: Path) -> None:
    path = tmp_path / "runtime-endurance.ndjson"
    path.write_text("reserved", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing existing endurance event log"):
        run_runtime_endurance_preflight(event_log=path, event_count=10, cycle_count=1)


def test_runtime_endurance_validates_arguments(tmp_path: Path) -> None:
    path = tmp_path / "runtime-endurance.ndjson"

    with pytest.raises(ValueError, match="event_count must be positive"):
        run_runtime_endurance_preflight(event_log=path, event_count=0)
