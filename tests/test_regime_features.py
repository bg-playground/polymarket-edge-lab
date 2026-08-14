from datetime import UTC, datetime
from decimal import Decimal

from polymarket_edge_lab.analysis.pair_sensitivity import SensitivityPairEvent
from polymarket_edge_lab.analysis.regime_features import build_regime_features
from polymarket_edge_lab.models.reconstruction import LedgerEntry


def _row(*, trade_id: str, epoch: int, side: str, price: str, shares: str, seq: int) -> LedgerEntry:
    return LedgerEntry(
        source_trade_id=trade_id,
        account="acct",
        market_id="m1",
        asset_id=side,
        outcome=side,
        side="BUY",
        timestamp=datetime.fromtimestamp(epoch, tz=UTC),
        price=Decimal(price),
        shares=Decimal(shares),
        notional=Decimal(price) * Decimal(shares),
        transaction_hash=f"tx-{trade_id}",
        outcome_index=0 if side == "UP" else 1,
        slug="btc-updown-5m-1000",
        event_slug=None,
        title=None,
        raw_page_path=None,
        raw_page_hash=None,
        page_offset=None,
        record_index=None,
        market_sequence_number=1,
        fill_sequence_number=seq,
        eligible_binary_market=True,
        market_exclusion_reason=None,
        normalized_outcome_side=side,  # type: ignore[arg-type]
        outcome_side_reason=None,
    )


def test_future_fill_does_not_change_current_feature_row() -> None:
    event = SensitivityPairEvent(
        method="fifo",
        market_id="m1",
        slug="btc-updown-5m-1000",
        formed_at_epoch=1100,
        paired_shares=Decimal("5"),
        pair_cost=Decimal("0.95"),
        lag_seconds=40,
        elapsed_seconds=100,
        transaction_hash="tx-down",
    )
    base = [
        _row(trade_id="up", epoch=1060, side="UP", price="0.45", shares="5", seq=1),
        _row(trade_id="down", epoch=1100, side="DOWN", price="0.50", shares="5", seq=2),
    ]
    future = _row(
        trade_id="future", epoch=1150, side="UP", price="0.99", shares="100", seq=3
    )
    before = build_regime_features(base, [event], complete_market_ids={"m1"})
    after = build_regime_features(base + [future], [event], complete_market_ids={"m1"})
    assert before == after
    assert before[0].inventory_imbalance == Decimal("0")
    assert before[0].fill_count_60s == 2
