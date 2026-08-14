from datetime import UTC, datetime
from decimal import Decimal

from polymarket_edge_lab.analysis.pair_sensitivity import (
    LATENCY_BUCKETS,
    TIME_BUCKETS,
    latency_bucket,
    market_time_bucket,
    pair_events_by_method,
    summarize_events,
)
from polymarket_edge_lab.models.trade import NormalizedTrade
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger

ACCOUNT = "0xabc0000000000000000000000000000000000000"


def _trade(trade_id: str, outcome: str, price: str, shares: str, ts: int) -> NormalizedTrade:
    return NormalizedTrade(
        source="polymarket-data-api",
        source_trade_id=trade_id,
        account=ACCOUNT,
        market_id="m1",
        asset_id=f"asset-{outcome}",
        timestamp=datetime.fromtimestamp(ts, tz=UTC),
        outcome=outcome,
        side="BUY",
        price=Decimal(price),
        shares=Decimal(shares),
        slug="btc-updown-5m-1200",
        raw_extra={},
    )


def test_fifo_and_lifo_can_differ() -> None:
    trades = [
        _trade("1", "UP", "0.20", "1", 1201),
        _trade("2", "UP", "0.60", "1", 1202),
        _trade("3", "DOWN", "0.50", "1", 1203),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    events, _ = pair_events_by_method(ledger, complete_market_ids={"m1"})
    fifo = summarize_events("fifo", events["fifo"])
    lifo = summarize_events("lifo", events["lifo"])
    assert fifo.weighted_pair_cost == Decimal("0.70")
    assert lifo.weighted_pair_cost == Decimal("1.10")


def test_weighted_average_uses_current_inventory_only() -> None:
    trades = [
        _trade("1", "UP", "0.20", "1", 1201),
        _trade("2", "UP", "0.60", "1", 1202),
        _trade("3", "DOWN", "0.50", "1", 1203),
        _trade("4", "UP", "0.01", "10", 1204),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    events, _ = pair_events_by_method(ledger, complete_market_ids={"m1"})
    weighted = events["weighted_average"]
    assert len(weighted) == 1
    assert weighted[0].pair_cost == Decimal("0.90")


def test_latency_bucket_boundaries() -> None:
    values = [0, 1, 2, 5, 6, 15, 16, 30, 31, 60, 61, 120, 121]
    expected = [
        "0s",
        "1s",
        "2-5s",
        "2-5s",
        "6-15s",
        "6-15s",
        "16-30s",
        "16-30s",
        "31-60s",
        "31-60s",
        "61-120s",
        "61-120s",
        ">120s",
    ]
    assert [latency_bucket(v) for v in values] == expected
    assert tuple(dict.fromkeys(expected)) == LATENCY_BUCKETS


def test_market_time_bucket_boundaries() -> None:
    assert market_time_bucket(-1) is None
    assert market_time_bucket(0) == "[0,30)"
    assert market_time_bucket(29) == "[0,30)"
    assert market_time_bucket(30) == "[30,60)"
    assert market_time_bucket(299) == "[270,300)"
    assert market_time_bucket(300) is None
    assert len(TIME_BUCKETS) == 10
