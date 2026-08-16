from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


def _event(sequence: int) -> EventEnvelope:
    return EventEnvelope(
        schema_version="m4a-event-v1",
        event_type="source_health",
        event_id=f"test:{sequence}",
        run_id="test",
        sequence=sequence,
        created_at=datetime(2026, 8, 16, tzinfo=UTC),
        payload={"source": "test", "status": "poll_ok"},
    )


def test_next_sequence_and_append_do_not_rescan_log(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    store = AppendOnlyEventStore(path)

    def unexpected_scan() -> object:
        raise AssertionError("steady-state append path must not rescan the durable log")

    store.iter_records = unexpected_scan  # type: ignore[method-assign, assignment]

    for sequence in range(100):
        assert store.next_sequence() == sequence
        store.append(_event(sequence))

    assert store.next_sequence() == 100


def test_reopen_validates_full_log_once_and_resumes_sequence(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    first = AppendOnlyEventStore(path)
    first.append(_event(0))
    first.append(_event(1))

    reopened = AppendOnlyEventStore(path)

    assert reopened.next_sequence() == 2
    reopened.append(_event(2))
    assert [record["sequence"] for record in reopened.iter_records()] == [0, 1, 2]


def test_stale_store_instance_fails_closed_on_external_append(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    first = AppendOnlyEventStore(path)
    second = AppendOnlyEventStore(path)

    first.append(_event(0))

    with pytest.raises(ValueError, match="changed outside this store instance"):
        second.next_sequence()


def test_constructor_rejects_non_contiguous_existing_log(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    valid = AppendOnlyEventStore(path)
    valid.append(_event(0))
    text = path.read_text(encoding="utf-8").replace('"sequence":0', '"sequence":2')
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="non-contiguous append-only sequence"):
        AppendOnlyEventStore(path)
