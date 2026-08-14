from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from polymarket_edge_lab.models.trade import NormalizedTrade


def test_notional_is_price_times_shares() -> None:
    trade = NormalizedTrade(
        source="fixture",
        source_trade_id="trade-1",
        account="0xabc",
        market_id="market-1",
        timestamp=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        outcome="UP",
        side="BUY",
        price=Decimal("0.44"),
        shares=Decimal("100"),
    )
    assert trade.notional == Decimal("44.00")


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NormalizedTrade(
            source="fixture",
            source_trade_id="trade-1",
            account="0xabc",
            market_id="market-1",
            timestamp=datetime(2026, 8, 14, 12, 0),
            outcome="UP",
            side="BUY",
            price=Decimal("0.44"),
            shares=Decimal("100"),
        )
