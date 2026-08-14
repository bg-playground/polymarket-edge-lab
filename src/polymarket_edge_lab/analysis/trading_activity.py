from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from decimal import Decimal

from polymarket_edge_lab.models.reconstruction import LedgerEntry

ZERO = Decimal("0")


@dataclass(frozen=True)
class TradingActivitySummary:
    total_trades: int
    active_hours: int
    trades_per_active_hour: Decimal | None
    average_trade_notional: Decimal | None


def summarize_trading_activity(ledger: list[LedgerEntry]) -> TradingActivitySummary:
    if not ledger:
        return TradingActivitySummary(0, 0, None, None)

    hour_buckets: set[str] = set()
    total_notional = ZERO
    for row in ledger:
        bucket = row.timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H")
        hour_buckets.add(bucket)
        total_notional += abs(row.notional)

    total_trades = len(ledger)
    active_hours = len(hour_buckets)
    tph = Decimal(total_trades) / Decimal(active_hours) if active_hours > 0 else None
    avg = total_notional / Decimal(total_trades) if total_trades > 0 else None
    return TradingActivitySummary(total_trades, active_hours, tph, avg)
