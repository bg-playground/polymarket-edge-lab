from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polymarket_edge_lab.shadow.binding import ProspectiveOutcomeBinder
from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.state_processor import LiveStateProcessor
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

RUN_ID = "incremental-test"
MARKET_ID = "0xmarket"
BASE_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _append(store: AppendOnlyEventStore, event_type: str, payload: dict[str, object], *, created_at: datetime = BASE_TIME) -> str:
    sequence = store.next_sequence()
    event_id = f"{RUN_ID}:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type=event_type,  # type: ignore[arg-type]
            event_id=event_id,
            run_id=RUN_ID,
            sequence=sequence,
            created_at=created_at,
            payload=payload,
        )
    )
    return event_id


def _unexpected_full_scan() -> object:
    raise AssertionError("steady-state live processing must not rescan from sequence zero")


def test_incremental_tail_reads_only_new_records(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append(store, "source_health", {"source": "test", "status": "poll_ok"})
    offset = store.end_offset()
    _append(store, "source_health", {"source": "test", "status": "poll_ok"})
    _append(store, "source_health", {"source": "test", "status": "poll_ok"})

    records, next_offset = store.read_records_from(offset)

    assert [record["sequence"] for record in records] == [1, 2]
    assert next_offset == store.end_offset()
    assert store.read_records_from(next_offset) == ([], next_offset)


def test_state_processor_steady_state_uses_incremental_tail(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    processor = LiveStateProcessor(run_id=RUN_ID, store=store)
    store.iter_records = _unexpected_full_scan  # type: ignore[method-assign, assignment]
    fill = NormalizedFill(
        source_trade_id="trade-1",
        market_id=MARKET_ID,
        asset_id="asset-up",
        outcome_side="UP",
        side="BUY",
        source_timestamp=BASE_TIME,
        price=Decimal("0.40"),
        shares=Decimal("2"),
        receive_timestamp=BASE_TIME + timedelta(milliseconds=20),
        local_ingest_id="local-1",
    )
    _append(store, "normalized_fill", fill.to_payload(), created_at=fill.receive_timestamp)

    result = processor.process_pending()

    assert result.processed_fill_count == 1
    assert result.pair_formation_count == 0
    assert processor.snapshot(MARKET_ID) is not None
    assert processor.process_pending().processed_fill_count == 0


def test_binder_incremental_index_preserves_strict_prior_boundary(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    binder = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store)
    store.iter_records = _unexpected_full_scan  # type: ignore[method-assign, assignment]
    prediction_id = _append(
        store,
        "prediction",
        {
            "market_id": MARKET_ID,
            "advancement_eligible_candidate": True,
            "event_conditioned_reconstruction": False,
            "score_id": "score-1",
        },
        created_at=BASE_TIME + timedelta(seconds=9, milliseconds=999),
    )
    pair_time = BASE_TIME + timedelta(seconds=10)
    _append(
        store,
        "pair_formation",
        {
            "normalized_fill_event_id": "fill-1",
            "pair_index": 0,
            "market_id": MARKET_ID,
            "completing_source_trade_id": "trade-2",
            "up_source_trade_id": "trade-1",
            "down_source_trade_id": "trade-2",
            "paired_shares": "1",
            "up_price": "0.4",
            "down_price": "0.5",
            "pair_cost": "0.9",
            "lag_seconds": 3,
            "formed_at_source_timestamp": pair_time.isoformat(),
            "formed_at_receive_timestamp": (pair_time + timedelta(milliseconds=10)).isoformat(),
        },
        created_at=pair_time + timedelta(milliseconds=10),
    )

    result = binder.process_pending()
    bindings = [
        record for record in store.iter_records.__self__._record_cache  # type: ignore[attr-defined, union-attr]
        if record.get("event_type") == "score_binding"
    ]

    assert result.bound_pair_count == 1
    assert result.unbound_pair_count == 0
    assert len(bindings) == 1
    assert bindings[0]["payload"]["prediction_event_id"] == prediction_id  # type: ignore[index]


def test_binder_excludes_exact_source_second_prediction(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    binder = ProspectiveOutcomeBinder(run_id=RUN_ID, store=store)
    pair_time = BASE_TIME + timedelta(seconds=10)
    _append(
        store,
        "prediction",
        {
            "market_id": MARKET_ID,
            "advancement_eligible_candidate": True,
            "event_conditioned_reconstruction": False,
            "score_id": "score-boundary",
        },
        created_at=pair_time,
    )
    _append(
        store,
        "pair_formation",
        {
            "normalized_fill_event_id": "fill-1",
            "pair_index": 0,
            "market_id": MARKET_ID,
            "completing_source_trade_id": "trade-2",
            "up_source_trade_id": "trade-1",
            "down_source_trade_id": "trade-2",
            "paired_shares": "1",
            "up_price": "0.4",
            "down_price": "0.5",
            "pair_cost": "0.9",
            "lag_seconds": 3,
            "formed_at_source_timestamp": pair_time.isoformat(),
            "formed_at_receive_timestamp": (pair_time + timedelta(milliseconds=10)).isoformat(),
        },
        created_at=pair_time + timedelta(milliseconds=10),
    )

    result = binder.process_pending()

    assert result.bound_pair_count == 0
    assert result.unbound_pair_count == 1
