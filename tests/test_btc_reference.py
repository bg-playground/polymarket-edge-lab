from decimal import Decimal

from polymarket_edge_lab.data.btc_reference import _parse_rows


def test_parse_coinbase_rows_sorts_and_maps_ohlc() -> None:
    rows = [
        [120, 98, 105, 100, 102, 10],
        [60, 95, 103, 99, 100, 11],
    ]
    candles = _parse_rows(rows)
    assert [candle.open_epoch for candle in candles] == [60, 120]
    assert candles[0].open == Decimal("99")
    assert candles[0].high == Decimal("103")
    assert candles[0].low == Decimal("95")
    assert candles[0].close == Decimal("100")
