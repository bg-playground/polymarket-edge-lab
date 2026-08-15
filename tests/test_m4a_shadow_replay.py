from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.replay import canonical_fill_key, replay_arrival_time
from polymarket_edge_lab.shadow.state import MarketOnlineState
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


def _fill(
    trade_id: str,
    side: str,
    outcome: str,
    shares: str,
    price: str,
    seconds: int,
) -> NormalizedFill:
    base = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    return NormalizedFill(
        source_trade_id=trade_id,
        market_id="market-1",
        asset_id=f"asset-{outcome.lower()}",
        outcome_side=outcome,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        source_timestamp=base + timedelta(seconds=seconds),
        price=Decimal(price),
        shares=Decimal(shares),
        receive_timestamp=base + timedelta(seconds=seconds, milliseconds=250),
        local_ingest_id=f"ingest-{trade_id}",
    )


def _event(fill: NormalizedFill, sequence: int) -> EventEnvelope:
    return EventEnvelope(
        schema_version="m4a-event-v1",
        event_type="normalized_fill",
        event_id=f"event-{sequence}",
        run_id="run-1",
        sequence=sequence,
        created_at=fill.receive_timestamp,
        payload=fill.to_payload(),
    )


def test_fifo_pair_formation_and_idempotence() -> None:
    state = MarketOnlineState("market-1")
    assert state.apply(_fill("u1", "BUY", "UP", "5", "0.44", 1)) == []
    formations = state.apply(_fill("d1", "BUY", "DOWN", "3", "0.51", 2))
    assert len(formations) == 1
    assert formations[0].paired_shares == Decimal("3")
    assert formations[0].pair_cost == Decimal("0.95")

    duplicate = state.apply(_fill("d1", "BUY", "DOWN", "3", "0.51", 2))
    assert duplicate == []
    snapshot = state.snapshot()
    assert snapshot.up_inventory == Decimal("5")
    assert snapshot.down_inventory == Decimal("3")
    assert snapshot.paired_inventory == Decimal("3")
    assert snapshot.residual_inventory == Decimal("2")
    assert snapshot.cumulative_paired_quantity == Decimal("3")
    assert snapshot.applied_fill_count == 2


def test_append_only_store_rejects_sequence_gaps(tmp_path: Path) -> None:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    fill = _fill("u1", "BUY", "UP", "1", "0.45", 1)
    store.append(_event(fill, 0))
    assert store.next_sequence() == 1

    try:
        store.append(_event(fill, 2))
    except ValueError as exc:
        assert "expected sequence 1" in str(exc)
    else:
        raise AssertionError("sequence gap must be rejected")


def test_arrival_time_replay_reproduces_live_state(tmp_path: Path) -> None:
    fills = [
        _fill("u1", "BUY", "UP", "5", "0.44", 1),
        _fill("d1", "BUY", "DOWN", "2", "0.50", 2),
        _fill("d2", "BUY", "DOWN", "3", "0.49", 3),
    ]
    live = MarketOnlineState("market-1")
    expected_formations = []
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    for sequence, fill in enumerate(fills):
        expected_formations.extend(live.apply(fill))
        store.append(_event(fill, sequence))

    replay = replay_arrival_time(store)
    assert replay.processed_events == 3
    assert replay.snapshots["market-1"] == live.snapshot()
    assert replay.pair_formations == expected_formations


def test_canonical_key_uses_source_id_before_local_ingest_tie_breaker() -> None:
    left = _fill("b", "BUY", "UP", "1", "0.4", 1)
    right = _fill("a", "BUY", "UP", "1", "0.4", 1)
    assert canonical_fill_key(right) < canonical_fill_key(left)
