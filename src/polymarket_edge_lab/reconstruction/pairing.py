from __future__ import annotations

from collections import deque
from decimal import Decimal

from polymarket_edge_lab.models.reconstruction import InventoryEvent, PairAccountingSummary

ZERO = Decimal("0")
ONE = Decimal("1")


def _fifo_inventory_cost(
    events: list[InventoryEvent], outcome_side: str, qty: Decimal
) -> Decimal | None:
    if qty <= ZERO:
        return None
    lots: deque[list[Decimal]] = deque()
    for event in events:
        if event.outcome_side != outcome_side:
            continue
        remaining = event.shares
        if event.side == "BUY":
            lots.append([event.shares, event.price])
            continue
        while remaining > ZERO and lots:
            lot = lots[0]
            take = min(remaining, lot[0])
            lot[0] -= take
            remaining -= take
            if lot[0] == ZERO:
                lots.popleft()

    need = qty
    cost = ZERO
    for lot_qty, lot_price in lots:
        if need <= ZERO:
            break
        take = min(need, lot_qty)
        cost += take * lot_price
        need -= take
    if need > ZERO:
        return None
    return cost


def summarize_pair_accounting(
    market_id: str,
    events: list[InventoryEvent],
) -> PairAccountingSummary:
    if not events:
        return PairAccountingSummary(
            market_id=market_id,
            paired_shares_formed=ZERO,
            weighted_pair_cost=None,
            weighted_gross_pair_edge=None,
            fifo_pair_cost=None,
            fifo_gross_pair_edge=None,
        )

    prev_paired = ZERO
    paired_shares_formed = ZERO

    for event in events:
        if event.paired_shares > prev_paired:
            paired_shares_formed += event.paired_shares - prev_paired
        prev_paired = event.paired_shares

    final = events[-1]
    final_pair_qty = min(max(final.up_inventory, ZERO), max(final.down_inventory, ZERO))
    weighted_pair_cost = None
    weighted_gross_edge = None
    if final_pair_qty > ZERO:
        weighted_pair_cost = (final.up_weighted_avg_buy_cost or ZERO) + (
            final.down_weighted_avg_buy_cost or ZERO
        )
        weighted_gross_edge = ONE - weighted_pair_cost

    fifo_pair_cost = None
    fifo_gross_edge = None
    if final_pair_qty > ZERO:
        up_cost = _fifo_inventory_cost(events, "UP", final_pair_qty)
        down_cost = _fifo_inventory_cost(events, "DOWN", final_pair_qty)
        if up_cost is not None and down_cost is not None:
            fifo_pair_cost = (up_cost + down_cost) / final_pair_qty
            fifo_gross_edge = ONE - fifo_pair_cost

    return PairAccountingSummary(
        market_id=market_id,
        paired_shares_formed=paired_shares_formed,
        weighted_pair_cost=weighted_pair_cost,
        weighted_gross_pair_edge=weighted_gross_edge,
        fifo_pair_cost=fifo_pair_cost,
        fifo_gross_pair_edge=fifo_gross_edge,
    )
