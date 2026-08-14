from datetime import UTC, datetime
from decimal import Decimal

from polymarket_edge_lab.models.trade import NormalizedTrade
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger


def _trade(trade_id: str, outcome: str) -> NormalizedTrade:
    return NormalizedTrade(
        source="polymarket-data-api",
        source_trade_id=trade_id,
        account="0xabc",
        market_id="m1",
        asset_id=f"asset-{outcome}",
        timestamp=datetime(2026, 8, 14, tzinfo=UTC),
        outcome=outcome,
        side="BUY",
        price=Decimal("0.5"),
        shares=Decimal("1"),
    )


def test_empty_complete_market_ids_marks_market_incomplete() -> None:
    ledger = build_canonical_ledger(
        [_trade("1", "UP"), _trade("2", "DOWN")],
        complete_market_ids=set(),
    )
    assert all(not row.eligible_binary_market for row in ledger)
    assert all(row.market_exclusion_reason == "unresolved_history_completeness" for row in ledger)


def test_none_complete_market_ids_preserves_unconstrained_behavior() -> None:
    ledger = build_canonical_ledger([_trade("1", "UP"), _trade("2", "DOWN")])
    assert all(row.eligible_binary_market for row in ledger)
