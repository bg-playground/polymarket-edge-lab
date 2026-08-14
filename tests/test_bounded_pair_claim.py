from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from polymarket_edge_lab.analysis.bounded_pair_claim import (
    fully_contained_btc_5m_market_ids,
    summarize_chronological_pair_formation,
)
from polymarket_edge_lab.models.trade import NormalizedTrade
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger

ACCOUNT = "0xabc0000000000000000000000000000000000000"


def _trade(
    trade_id: str,
    *,
    market_id: str,
    slug: str,
    outcome: str,
    side: str = "BUY",
    price: str,
    shares: str,
    timestamp: int,
) -> NormalizedTrade:
    return NormalizedTrade(
        source="polymarket-data-api",
        source_trade_id=trade_id,
        account=ACCOUNT,
        market_id=market_id,
        asset_id=f"asset-{outcome}",
        timestamp=datetime.fromtimestamp(timestamp, tz=UTC),
        outcome=outcome,
        side=side,  # type: ignore[arg-type]
        price=Decimal(price),
        shares=Decimal(shares),
        slug=slug,
        raw_extra={},
    )


def test_fully_contained_btc_5m_cohort() -> None:
    trades = [
        _trade(
            "a",
            market_id="before",
            slug="btc-updown-5m-900",
            outcome="UP",
            price="0.4",
            shares="1",
            timestamp=1000,
        ),
        _trade(
            "b",
            market_id="inside",
            slug="btc-updown-5m-1200",
            outcome="UP",
            price="0.4",
            shares="1",
            timestamp=1201,
        ),
        _trade(
            "c",
            market_id="after",
            slug="btc-updown-5m-1800",
            outcome="UP",
            price="0.4",
            shares="1",
            timestamp=1801,
        ),
        _trade(
            "d",
            market_id="other",
            slug="eth-updown-5m-1200",
            outcome="UP",
            price="0.4",
            shares="1",
            timestamp=1201,
        ),
    ]
    assert fully_contained_btc_5m_market_ids(
        trades, collection_start=1000, collection_end=2000
    ) == {"inside"}


def test_chronological_fifo_pair_formation_cost() -> None:
    trades = [
        _trade(
            "1",
            market_id="m1",
            slug="btc-updown-5m-1200",
            outcome="UP",
            price="0.40",
            shares="10",
            timestamp=1201,
        ),
        _trade(
            "2",
            market_id="m1",
            slug="btc-updown-5m-1200",
            outcome="DOWN",
            price="0.55",
            shares="4",
            timestamp=1202,
        ),
        _trade(
            "3",
            market_id="m1",
            slug="btc-updown-5m-1200",
            outcome="DOWN",
            price="0.50",
            shares="6",
            timestamp=1203,
        ),
    ]
    complete = {"m1"}
    ledger = build_canonical_ledger(trades, complete_market_ids=complete)
    summary, events = summarize_chronological_pair_formation(ledger, complete_market_ids=complete)
    assert summary.market_count == 1
    assert summary.paired_shares == Decimal("10")
    assert summary.weighted_pair_cost == Decimal("0.92")
    assert summary.weighted_gross_pair_edge == Decimal("0.08")
    assert len(events) == 2


def test_sell_market_is_excluded_from_buy_lot_pair_claim() -> None:
    trades = [
        _trade(
            "1",
            market_id="m1",
            slug="btc-updown-5m-1200",
            outcome="UP",
            price="0.40",
            shares="10",
            timestamp=1201,
        ),
        _trade(
            "2",
            market_id="m1",
            slug="btc-updown-5m-1200",
            outcome="DOWN",
            price="0.50",
            shares="10",
            timestamp=1202,
        ),
        _trade(
            "3",
            market_id="m1",
            slug="btc-updown-5m-1200",
            outcome="UP",
            side="SELL",
            price="0.60",
            shares="1",
            timestamp=1203,
        ),
    ]
    ledger = build_canonical_ledger(trades, complete_market_ids={"m1"})
    summary, events = summarize_chronological_pair_formation(ledger, complete_market_ids={"m1"})
    assert summary.market_count == 0
    assert summary.excluded_sell_markets == ("m1",)
    assert summary.weighted_pair_cost is None
    assert events == []
