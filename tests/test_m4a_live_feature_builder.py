from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.feature_builder import LiveStage3GFeatureBuilder
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

RUN_ID = "run-live"
MARKET = "0x" + "1" * 64
START = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
START_EPOCH = int(START.timestamp())


def _append(
    store: AppendOnlyEventStore,
    event_type: str,
    created_at: datetime,
    payload: dict[str, object],
) -> str:
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


def _append_metadata(store: AppendOnlyEventStore) -> None:
    metadata = {
        "condition_id": MARKET,
        "gamma_market_id": "123",
        "slug": f"btc-updown-5m-{START_EPOCH}",
        "question": "Bitcoin Up or Down",
        "market_start_epoch": START_EPOCH,
        "market_end_epoch": START_EPOCH + 300,
        "up_token_id": "asset-up",
        "down_token_id": "asset-down",
        "active": True,
        "closed": False,
        "accepting_orders": True,
        "raw_observation_sha256": "a" * 64,
    }
    _append(
        store,
        "market_metadata",
        START,
        {
            "condition_id": MARKET,
            "eligible": True,
            "reason_code": "eligible",
            "metadata": metadata,
        },
    )


def _append_health(store: AppendOnlyEventStore, at: datetime) -> None:
    _append(
        store,
        "source_health",
        at,
        {
            "source": "polymarket-data-api",
            "status": "poll_ok",
            "detail": "ok",
            "raw_observation_event_id": None,
        },
    )


def _append_btc_candle(
    store: AppendOnlyEventStore,
    *,
    open_at: datetime,
    open_price: str,
    high: str,
    low: str,
    close: str,
    observed_at: datetime,
) -> None:
    open_epoch = int(open_at.timestamp())
    _append(
        store,
        "btc_candle",
        observed_at,
        {
            "source": "coinbase-exchange-rest",
            "product_id": "BTC-USD",
            "open_epoch": open_epoch,
            "close_epoch": open_epoch + 60,
            "interval_seconds": 60,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": "1",
            "candle_fingerprint": "f" * 64,
            "raw_observation_event_id": "raw",
            "response_sha256": "b" * 64,
            "causal_at_observation": True,
        },
    )


def _append_fill(
    store: AppendOnlyEventStore,
    *,
    trade_id: str,
    side: str,
    outcome: str,
    shares: str,
    seconds: int,
) -> None:
    source_time = START + timedelta(seconds=seconds)
    fill = NormalizedFill(
        source_trade_id=trade_id,
        market_id=MARKET,
        asset_id=f"asset-{outcome.lower()}",
        outcome_side=outcome,  # type: ignore[arg-type]
        side=side,  # type: ignore[arg-type]
        source_timestamp=source_time,
        price=Decimal("0.45"),
        shares=Decimal(shares),
        receive_timestamp=source_time + timedelta(milliseconds=100),
        local_ingest_id=f"ingest-{trade_id}",
    )
    fill_event_id = _append(store, "normalized_fill", fill.receive_timestamp, fill.to_payload())
    _append(
        store,
        "state_application",
        fill.receive_timestamp,
        {
            "normalized_fill_event_id": fill_event_id,
            "source_trade_id": trade_id,
            "market_id": MARKET,
            "status": "applied",
            "snapshot": {"quarantined": False},
        },
    )


def _base_store(tmp_path: Path, *, health_at: datetime | None = None) -> AppendOnlyEventStore:
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    _append_metadata(store)
    _append_btc_candle(
        store,
        open_at=START - timedelta(seconds=60),
        open_price="60000",
        high="60020",
        low="59990",
        close="60010",
        observed_at=START + timedelta(milliseconds=10),
    )
    _append_btc_candle(
        store,
        open_at=START,
        open_price="60010",
        high="60050",
        low="60000",
        close="60040",
        observed_at=START + timedelta(seconds=60, milliseconds=10),
    )
    _append_btc_candle(
        store,
        open_at=START + timedelta(seconds=60),
        open_price="60040",
        high="60100",
        low="60030",
        close="60090",
        observed_at=START + timedelta(seconds=120, milliseconds=10),
    )
    _append_health(store, health_at or START + timedelta(seconds=129))
    return store


def test_builder_emits_exact_frozen_feature_order_and_buy_only_state(tmp_path: Path) -> None:
    store = _base_store(tmp_path)
    _append_fill(store, trade_id="up-1", side="BUY", outcome="UP", shares="2", seconds=20)
    _append_fill(store, trade_id="down-1", side="BUY", outcome="DOWN", shares="1", seconds=40)
    _append_fill(store, trade_id="sell-1", side="SELL", outcome="UP", shares="0.5", seconds=100)
    _append_health(store, START + timedelta(seconds=129))

    builder = LiveStage3GFeatureBuilder(run_id=RUN_ID, store=store)
    result = builder.build_tick(market_id=MARKET, tick_time=START + timedelta(seconds=130))

    assert result.scorable is True
    record = list(store.iter_records())[-1]
    assert record["event_type"] == "feature_snapshot"
    payload = record["payload"]
    assert isinstance(payload, dict)
    assert payload["feature_order"] == list(MODEL_FEATURES["hgb_all_pre_event"])
    features = payload["features"]
    assert isinstance(features, dict)
    assert tuple(features) == MODEL_FEATURES["hgb_all_pre_event"]
    assert features["elapsed_seconds"] == 130
    assert features["seconds_remaining"] == 170
    assert features["up_inventory"] == 2.0
    assert features["down_inventory"] == 1.0
    assert features["paired_inventory"] == 1.0
    assert features["cumulative_paired_quantity"] == 1.0
    assert features["seconds_since_last_up_fill"] == 110
    assert features["seconds_since_last_down_fill"] == 90
    assert features["fill_count_60s"] == 0
    assert features["btc_return_60s"] is not None
    assert features["btc_return_120s"] is not None
    assert payload["applied_buy_fill_count"] == 2


def test_builder_rejects_stale_btc_reference(tmp_path: Path) -> None:
    tick = START + timedelta(seconds=250)
    store = _base_store(tmp_path, health_at=tick - timedelta(seconds=1))
    builder = LiveStage3GFeatureBuilder(run_id=RUN_ID, store=store)

    result = builder.build_tick(market_id=MARKET, tick_time=tick)

    assert result.scorable is False
    assert result.reason_code == "btc_reference_stale"
    record = list(store.iter_records())[-1]
    assert record["event_type"] == "unscorable_tick"


def test_builder_rejects_stale_target_source(tmp_path: Path) -> None:
    store = _base_store(tmp_path, health_at=START + timedelta(seconds=120))
    builder = LiveStage3GFeatureBuilder(run_id=RUN_ID, store=store)

    result = builder.build_tick(market_id=MARKET, tick_time=START + timedelta(seconds=130))

    assert result.scorable is False
    assert result.reason_code == "target_source_stale"


def test_builder_rejects_quarantined_market(tmp_path: Path) -> None:
    store = _base_store(tmp_path)
    _append(
        store,
        "state_quarantine",
        START + timedelta(seconds=125),
        {
            "market_id": MARKET,
            "source_trade_id": "sell-1",
            "reason_code": "sell_would_unwind_paired_inventory",
            "detail": "ambiguous",
            "normalized_fill_event_id": "fill",
        },
    )
    _append_health(store, START + timedelta(seconds=129))
    builder = LiveStage3GFeatureBuilder(run_id=RUN_ID, store=store)

    result = builder.build_tick(market_id=MARKET, tick_time=START + timedelta(seconds=130))

    assert result.scorable is False
    assert result.reason_code == "market_state_quarantined"


def test_as_of_sequence_excludes_later_fill(tmp_path: Path) -> None:
    store = _base_store(tmp_path)
    _append_fill(store, trade_id="up-1", side="BUY", outcome="UP", shares="2", seconds=20)
    cutoff = store.next_sequence() - 1
    _append_fill(store, trade_id="down-late", side="BUY", outcome="DOWN", shares="1", seconds=30)
    _append_health(store, START + timedelta(seconds=129))
    builder = LiveStage3GFeatureBuilder(run_id=RUN_ID, store=store)

    result = builder.build_tick(
        market_id=MARKET,
        tick_time=START + timedelta(seconds=130),
        as_of_sequence=cutoff,
    )

    assert result.scorable is True
    record = list(store.iter_records())[-1]
    payload = record["payload"]
    assert isinstance(payload, dict)
    features = payload["features"]
    assert isinstance(features, dict)
    assert features["up_inventory"] == 2.0
    assert features["down_inventory"] == 0.0
