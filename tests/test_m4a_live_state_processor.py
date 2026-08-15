from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.state_processor import LiveStateProcessor
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

MARKET = "0xmarket"
BASE = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _fill(
    source_trade_id: str,
    side: str,
    outcome: str,
    shares: str,
    price: str,
    seconds: int,
) -> NormalizedFill:
    return NormalizedFill(
        source_trade_id=source_trade_id,
        market_id=MARKET,
        asset_id=f"asset-{outcome.lower()}",
        outcome_side=outcome,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        source_timestamp=BASE + timedelta(seconds=seconds),
        price=Decimal(price),
        shares=Decimal(shares),
        receive_timestamp=BASE + timedelta(seconds=seconds, milliseconds=100),
        local_ingest_id=f"ingest-{source_trade_id}",
    )


def _append_fill(store: AppendOnlyEventStore, fill: NormalizedFill) -> str:
    sequence = store.next_sequence()
    event_id = f"run:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type="normalized_fill",
            event_id=event_id,
            run_id="run",
            sequence=sequence,
            created_at=fill.receive_timestamp,
            payload=fill.to_payload(),
        )
    )
    return event_id


def test_processor_emits_application_and_pair_provenance(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_fill(store, _fill("up-1", "BUY", "UP", "3", "0.44", 2))
    completing_event_id = _append_fill(
        store, _fill("down-1", "BUY", "DOWN", "2", "0.51", 7)
    )

    processor = LiveStateProcessor(run_id="run", store=store)
    result = processor.process_pending()

    assert result.processed_fill_count == 2
    assert result.pair_formation_count == 1
    assert result.quarantine_count == 0
    records = list(store.iter_records())
    pairs = [record for record in records if record["event_type"] == "pair_formation"]
    assert len(pairs) == 1
    payload = pairs[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["normalized_fill_event_id"] == completing_event_id
    assert payload["up_source_trade_id"] == "up-1"
    assert payload["down_source_trade_id"] == "down-1"
    assert payload["paired_shares"] == "2"
    assert payload["pair_cost"] == "0.95"
    assert payload["lag_seconds"] == 5
    applications = [record for record in records if record["event_type"] == "state_application"]
    assert len(applications) == 2
    snapshot = processor.snapshot(MARKET)
    assert snapshot is not None
    assert snapshot.up_inventory == Decimal("3")
    assert snapshot.down_inventory == Decimal("2")
    assert snapshot.paired_inventory == Decimal("2")


def test_application_ack_makes_no_pair_fill_restart_idempotent(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_fill(store, _fill("up-1", "BUY", "UP", "1", "0.40", 1))

    first = LiveStateProcessor(run_id="run", store=store)
    assert first.process_pending().processed_fill_count == 1
    restarted = LiveStateProcessor(run_id="run", store=store)
    result = restarted.process_pending()

    assert result.processed_fill_count == 0
    records = list(store.iter_records())
    assert sum(record["event_type"] == "state_application" for record in records) == 1


def test_ambiguous_sell_emits_one_quarantine_and_blocks_later_fill(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_fill(store, _fill("up-1", "BUY", "UP", "2", "0.44", 1))
    _append_fill(store, _fill("down-1", "BUY", "DOWN", "2", "0.50", 2))
    _append_fill(store, _fill("sell-1", "SELL", "UP", "1", "0.60", 3))
    _append_fill(store, _fill("up-2", "BUY", "UP", "1", "0.41", 4))

    processor = LiveStateProcessor(run_id="run", store=store)
    result = processor.process_pending()

    assert result.quarantine_count == 1
    records = list(store.iter_records())
    quarantines = [record for record in records if record["event_type"] == "state_quarantine"]
    assert len(quarantines) == 1
    applications = [
        record["payload"] for record in records if record["event_type"] == "state_application"
    ]
    statuses = [payload["status"] for payload in applications if isinstance(payload, dict)]
    assert statuses == ["applied", "applied", "quarantined", "blocked_quarantined"]
    snapshot = processor.snapshot(MARKET)
    assert snapshot is not None
    assert snapshot.quarantined is True
    assert snapshot.applied_fill_count == 2


def test_restart_restores_pair_and_quarantine_state_without_duplicate_outputs(
    tmp_path: Path,
) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_fill(store, _fill("up-1", "BUY", "UP", "2", "0.44", 1))
    _append_fill(store, _fill("down-1", "BUY", "DOWN", "2", "0.50", 2))
    _append_fill(store, _fill("sell-1", "SELL", "UP", "1", "0.60", 3))

    first = LiveStateProcessor(run_id="run", store=store)
    first.process_pending()
    before = list(store.iter_records())
    restarted = LiveStateProcessor(run_id="run", store=store)
    result = restarted.process_pending()
    after = list(store.iter_records())

    assert result.processed_fill_count == 0
    assert result.pair_formation_count == 0
    assert result.quarantine_count == 0
    assert after == before
    snapshot = restarted.snapshot(MARKET)
    assert snapshot is not None
    assert snapshot.quarantined is True
    assert snapshot.paired_inventory == Decimal("2")
