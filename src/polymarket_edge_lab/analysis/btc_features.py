from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt

ZERO = Decimal("0")


@dataclass(frozen=True)
class BtcCandle:
    open_epoch: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    interval_seconds: int = 1

    @property
    def close_epoch(self) -> int:
        return self.open_epoch + self.interval_seconds


@dataclass(frozen=True)
class BtcFeatureRow:
    event_epoch: int
    reference_epoch: int | None
    reference_price: Decimal | None
    return_15s: Decimal | None
    return_30s: Decimal | None
    return_60s: Decimal | None
    return_120s: Decimal | None
    realized_vol_30s: Decimal | None
    realized_vol_60s: Decimal | None
    realized_vol_120s: Decimal | None
    absolute_return_60s: Decimal | None
    return_since_market_start: Decimal | None
    range_since_market_start: Decimal | None


def _safe_return(current: Decimal, previous: Decimal | None) -> Decimal | None:
    if previous is None or previous == ZERO:
        return None
    return current / previous - Decimal("1")


def _sample_std(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, start=ZERO) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), start=ZERO) / Decimal(len(values) - 1)
    return Decimal(str(sqrt(float(variance))))


def _close_at_or_before(candles: list[BtcCandle], epoch: int) -> Decimal | None:
    candidates = [candle.close for candle in candles if candle.close_epoch <= epoch]
    return candidates[-1] if candidates else None


def _returns(candles: list[BtcCandle], start_epoch: int, end_epoch: int) -> list[Decimal]:
    selected: list[Decimal] = []
    for candle in candles:
        if start_epoch < candle.close_epoch <= end_epoch:
            selected.append(candle.close)

    returns: list[Decimal] = []
    for left, right in zip(selected, selected[1:], strict=False):
        value = _safe_return(right, left)
        if value is not None:
            returns.append(value)
    return returns


def build_btc_features(
    candles: list[BtcCandle], *, event_epoch: int, market_start_epoch: int | None
) -> BtcFeatureRow:
    """Align only candles whose close is observable at or before event_epoch."""
    causal = sorted(
        (candle for candle in candles if candle.close_epoch <= event_epoch),
        key=lambda candle: candle.open_epoch,
    )
    if not causal:
        return BtcFeatureRow(
            event_epoch=event_epoch,
            reference_epoch=None,
            reference_price=None,
            return_15s=None,
            return_30s=None,
            return_60s=None,
            return_120s=None,
            realized_vol_30s=None,
            realized_vol_60s=None,
            realized_vol_120s=None,
            absolute_return_60s=None,
            return_since_market_start=None,
            range_since_market_start=None,
        )

    latest = causal[-1]
    current = latest.close

    def trailing_return(seconds: int) -> Decimal | None:
        return _safe_return(current, _close_at_or_before(causal, event_epoch - seconds))

    ret60 = trailing_return(60)
    start_price = (
        _close_at_or_before(causal, market_start_epoch) if market_start_epoch is not None else None
    )
    since_start = _safe_return(current, start_price)
    range_since_start = None
    if market_start_epoch is not None:
        market_candles: list[BtcCandle] = []
        for candle in causal:
            if candle.close_epoch >= market_start_epoch:
                market_candles.append(candle)

        if market_candles and start_price not in {None, ZERO}:
            high = max(candle.high for candle in market_candles)
            low = min(candle.low for candle in market_candles)
            range_since_start = (high - low) / start_price

    return BtcFeatureRow(
        event_epoch=event_epoch,
        reference_epoch=latest.close_epoch,
        reference_price=current,
        return_15s=trailing_return(15),
        return_30s=trailing_return(30),
        return_60s=ret60,
        return_120s=trailing_return(120),
        realized_vol_30s=_sample_std(_returns(causal, event_epoch - 30, event_epoch)),
        realized_vol_60s=_sample_std(_returns(causal, event_epoch - 60, event_epoch)),
        realized_vol_120s=_sample_std(_returns(causal, event_epoch - 120, event_epoch)),
        absolute_return_60s=abs(ret60) if ret60 is not None else None,
        return_since_market_start=since_start,
        range_since_market_start=range_since_start,
    )
