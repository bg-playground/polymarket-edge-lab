from decimal import Decimal

from polymarket_edge_lab.analysis.btc_features import BtcCandle, build_btc_features


def _candle(epoch: int, price: str) -> BtcCandle:
    value = Decimal(price)
    return BtcCandle(
        open_epoch=epoch,
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
    )


def test_future_candle_does_not_change_event_features() -> None:
    candles = [_candle(epoch, str(100 + epoch - 1000)) for epoch in range(1000, 1100)]
    before = build_btc_features(candles, event_epoch=1090, market_start_epoch=1000)
    after = build_btc_features(
        candles + [_candle(1095, "10000")], event_epoch=1090, market_start_epoch=1000
    )
    assert before == after
    assert before.reference_epoch is not None
    assert before.reference_epoch <= 1090


def test_candle_closing_after_event_is_excluded() -> None:
    result = build_btc_features(
        [_candle(1000, "100"), _candle(1001, "101")],
        event_epoch=1001,
        market_start_epoch=1000,
    )
    assert result.reference_epoch == 1001
    assert result.reference_price == Decimal("100")
