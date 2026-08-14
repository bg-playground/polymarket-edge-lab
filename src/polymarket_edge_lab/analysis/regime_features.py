from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from polymarket_edge_lab.analysis.bounded_pair_claim import btc_5m_market_start
from polymarket_edge_lab.analysis.pair_sensitivity import SensitivityPairEvent
from polymarket_edge_lab.models.reconstruction import LedgerEntry

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class RegimeFeatureRow:
    market_id: str
    slug: str | None
    formed_at_epoch: int
    paired_shares: Decimal
    pair_cost: Decimal
    favorable: bool
    strong_favorable: bool
    lag_seconds: int | None
    elapsed_seconds: int | None
    seconds_remaining: int | None
    up_inventory: Decimal
    down_inventory: Decimal
    paired_inventory: Decimal
    residual_inventory: Decimal
    inventory_imbalance: Decimal | None
    cumulative_up_vwap: Decimal | None
    cumulative_down_vwap: Decimal | None
    implied_complete_set_cost: Decimal | None
    seconds_since_last_up_fill: int | None
    seconds_since_last_down_fill: int | None
    fill_count_15s: int
    fill_count_30s: int
    fill_count_60s: int
    fill_qty_15s: Decimal
    fill_qty_30s: Decimal
    fill_qty_60s: Decimal
    side_switches_60s: int
    cumulative_paired_quantity: Decimal
    same_second_fill_count: int
    transaction_hash: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _FillState:
    epoch: int
    side: str
    shares: Decimal


def _seconds_since(now: datetime, then: datetime | None) -> int | None:
    if then is None:
        return None
    return max(0, int((now - then).total_seconds()))


def _trailing(fills: deque[_FillState], now_epoch: int, seconds: int) -> tuple[int, Decimal]:
    cutoff = now_epoch - seconds
    selected = [fill for fill in fills if fill.epoch >= cutoff]
    return len(selected), sum((fill.shares for fill in selected), start=ZERO)


def _switches(fills: deque[_FillState], now_epoch: int, seconds: int) -> int:
    cutoff = now_epoch - seconds
    sides = [fill.side for fill in fills if fill.epoch >= cutoff]
    return sum(1 for left, right in zip(sides, sides[1:], strict=False) if left != right)


def build_regime_features(
    ledger: list[LedgerEntry],
    fifo_events: list[SensitivityPairEvent],
    *,
    complete_market_ids: set[str],
) -> list[RegimeFeatureRow]:
    """Build deterministic event-time features without consulting future fills."""
    rows_by_market: dict[str, list[LedgerEntry]] = defaultdict(list)
    for row in ledger:
        if (
            row.market_id in complete_market_ids
            and row.eligible_binary_market
            and row.side == "BUY"
            and row.normalized_outcome_side in {"UP", "DOWN"}
        ):
            rows_by_market[row.market_id].append(row)

    events_by_market: dict[str, list[SensitivityPairEvent]] = defaultdict(list)
    for event in fifo_events:
        if event.market_id in complete_market_ids:
            events_by_market[event.market_id].append(event)

    result: list[RegimeFeatureRow] = []
    for market_id, events in events_by_market.items():
        market_rows = sorted(
            rows_by_market.get(market_id, []),
            key=lambda row: (row.timestamp, row.fill_sequence_number),
        )
        events_sorted = sorted(events, key=lambda event: event.formed_at_epoch)
        cursor = 0
        qty = {"UP": ZERO, "DOWN": ZERO}
        cost = {"UP": ZERO, "DOWN": ZERO}
        last_ts: dict[str, datetime | None] = {"UP": None, "DOWN": None}
        recent: deque[_FillState] = deque()
        cumulative_paired = ZERO

        for event in events_sorted:
            while cursor < len(market_rows):
                row = market_rows[cursor]
                epoch = int(row.timestamp.timestamp())
                if epoch > event.formed_at_epoch:
                    break
                side = row.normalized_outcome_side
                if side not in {"UP", "DOWN"}:
                    cursor += 1
                    continue
                qty[side] += row.shares
                cost[side] += row.shares * row.price
                last_ts[side] = row.timestamp
                recent.append(_FillState(epoch=epoch, side=side, shares=row.shares))
                cursor += 1

            while recent and recent[0].epoch < event.formed_at_epoch - 120:
                recent.popleft()

            up_vwap = cost["UP"] / qty["UP"] if qty["UP"] > ZERO else None
            down_vwap = cost["DOWN"] / qty["DOWN"] if qty["DOWN"] > ZERO else None
            implied = up_vwap + down_vwap if up_vwap is not None and down_vwap is not None else None
            paired_inventory = min(qty["UP"], qty["DOWN"])
            residual = abs(qty["UP"] - qty["DOWN"])
            total = qty["UP"] + qty["DOWN"]
            imbalance = (qty["UP"] - qty["DOWN"]) / total if total > ZERO else None
            cumulative_paired += event.paired_shares
            now = datetime.fromtimestamp(event.formed_at_epoch, tz=market_rows[0].timestamp.tzinfo)
            count15, qty15 = _trailing(recent, event.formed_at_epoch, 15)
            count30, qty30 = _trailing(recent, event.formed_at_epoch, 30)
            count60, qty60 = _trailing(recent, event.formed_at_epoch, 60)
            same_second = sum(1 for fill in recent if fill.epoch == event.formed_at_epoch)
            start = btc_5m_market_start(event.slug)
            elapsed = event.formed_at_epoch - start if start is not None else event.elapsed_seconds
            remaining = 300 - elapsed if elapsed is not None else None

            result.append(
                RegimeFeatureRow(
                    market_id=market_id,
                    slug=event.slug,
                    formed_at_epoch=event.formed_at_epoch,
                    paired_shares=event.paired_shares,
                    pair_cost=event.pair_cost,
                    favorable=event.pair_cost < ONE,
                    strong_favorable=event.pair_cost <= Decimal("0.98"),
                    lag_seconds=event.lag_seconds,
                    elapsed_seconds=elapsed,
                    seconds_remaining=remaining,
                    up_inventory=qty["UP"],
                    down_inventory=qty["DOWN"],
                    paired_inventory=paired_inventory,
                    residual_inventory=residual,
                    inventory_imbalance=imbalance,
                    cumulative_up_vwap=up_vwap,
                    cumulative_down_vwap=down_vwap,
                    implied_complete_set_cost=implied,
                    seconds_since_last_up_fill=_seconds_since(now, last_ts["UP"]),
                    seconds_since_last_down_fill=_seconds_since(now, last_ts["DOWN"]),
                    fill_count_15s=count15,
                    fill_count_30s=count30,
                    fill_count_60s=count60,
                    fill_qty_15s=qty15,
                    fill_qty_30s=qty30,
                    fill_qty_60s=qty60,
                    side_switches_60s=_switches(recent, event.formed_at_epoch, 60),
                    cumulative_paired_quantity=cumulative_paired,
                    same_second_fill_count=same_second,
                    transaction_hash=event.transaction_hash,
                )
            )
    return sorted(result, key=lambda row: (row.formed_at_epoch, row.market_id))
