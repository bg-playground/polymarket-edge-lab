from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from polymarket_edge_lab.models.reconstruction import InventoryEvent, LedgerEntry, OutcomeSide

ZERO = Decimal("0")


class _OutcomeInventory:
    def __init__(self) -> None:
        self.net_shares = ZERO
        self.buy_cost = ZERO
        self.shares_bought = ZERO
        self.shares_sold = ZERO

    @property
    def weighted_avg_buy_cost(self) -> Decimal | None:
        if self.net_shares <= ZERO:
            return None
        return self.buy_cost / self.net_shares

    def apply_buy(self, shares: Decimal, price: Decimal) -> None:
        self.net_shares += shares
        self.buy_cost += shares * price
        self.shares_bought += shares

    def apply_sell(self, shares: Decimal) -> Decimal | None:
        available_long = max(self.net_shares, ZERO)
        avg = self.weighted_avg_buy_cost
        self.net_shares -= shares
        self.shares_sold += shares
        remaining_long = max(self.net_shares, ZERO)
        if avg is not None:
            self.buy_cost = avg * remaining_long
        elif self.net_shares <= ZERO:
            self.buy_cost = ZERO
        if self.net_shares == ZERO:
            self.buy_cost = ZERO

        if shares > available_long:
            return shares - available_long
        return None


def reconstruct_inventory(ledger: list[LedgerEntry]) -> dict[str, list[InventoryEvent]]:
    by_market: dict[str, list[LedgerEntry]] = defaultdict(list)
    for row in ledger:
        by_market[row.market_id].append(row)

    out: dict[str, list[InventoryEvent]] = {}
    for market_id, rows in by_market.items():
        ordered = sorted(
            rows, key=lambda r: (r.timestamp, r.fill_sequence_number, r.source_trade_id)
        )
        up = _OutcomeInventory()
        down = _OutcomeInventory()
        events: list[InventoryEvent] = []

        for row in ordered:
            if not row.eligible_binary_market or row.normalized_outcome_side is None:
                continue
            inv = up if row.normalized_outcome_side == "UP" else down
            inventory_anomaly_reason: str | None = None
            if row.side == "BUY":
                inv.apply_buy(row.shares, row.price)
            else:
                oversold_shares = inv.apply_sell(row.shares)
                if oversold_shares is not None:
                    inventory_anomaly_reason = f"sell_exceeds_long_inventory_by={oversold_shares}"

            up_pos = max(up.net_shares, ZERO)
            down_pos = max(down.net_shares, ZERO)
            paired = min(up_pos, down_pos)
            directional_up = max(up_pos - down_pos, ZERO)
            directional_down = max(down_pos - up_pos, ZERO)
            directional_side: OutcomeSide | None = None
            directional_shares = ZERO
            if directional_up > ZERO:
                directional_side = "UP"
                directional_shares = directional_up
            elif directional_down > ZERO:
                directional_side = "DOWN"
                directional_shares = directional_down

            events.append(
                InventoryEvent(
                    market_id=market_id,
                    source_trade_id=row.source_trade_id,
                    timestamp=row.timestamp,
                    side=row.side,
                    outcome_side=row.normalized_outcome_side,
                    price=row.price,
                    shares=row.shares,
                    up_inventory=up.net_shares,
                    down_inventory=down.net_shares,
                    paired_shares=paired,
                    directional_side=directional_side,
                    directional_shares=directional_shares,
                    up_buy_cost=up.buy_cost,
                    down_buy_cost=down.buy_cost,
                    up_weighted_avg_buy_cost=up.weighted_avg_buy_cost,
                    down_weighted_avg_buy_cost=down.weighted_avg_buy_cost,
                    inventory_anomaly_reason=inventory_anomaly_reason,
                )
            )

        out[market_id] = events
    return out
