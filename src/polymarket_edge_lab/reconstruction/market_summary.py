from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from polymarket_edge_lab.models.reconstruction import (
    InventoryEvent,
    LedgerEntry,
    MarketSummary,
    PairAccountingSummary,
)

ZERO = Decimal("0")


def build_market_summaries(
    ledger: list[LedgerEntry],
    inventory_by_market: dict[str, list[InventoryEvent]],
    pairing_by_market: dict[str, PairAccountingSummary],
) -> list[MarketSummary]:
    by_market: dict[str, list[LedgerEntry]] = defaultdict(list)
    for row in ledger:
        by_market[row.market_id].append(row)

    summaries: list[MarketSummary] = []
    for market_id, rows in by_market.items():
        ordered = sorted(rows, key=lambda r: (r.timestamp, r.fill_sequence_number))
        inventory = inventory_by_market.get(market_id, [])
        final = inventory[-1] if inventory else None
        pairing = pairing_by_market.get(market_id)

        total_buy_notional = sum((r.notional for r in ordered if r.side == "BUY"), start=ZERO)
        total_sell_notional = sum((r.notional for r in ordered if r.side == "SELL"), start=ZERO)
        history_complete = all(r.eligible_binary_market for r in ordered) if ordered else False
        warnings = sorted(
            {r.market_exclusion_reason for r in ordered if r.market_exclusion_reason is not None}
        )

        max_paired = max((e.paired_shares for e in inventory), default=ZERO)

        summaries.append(
            MarketSummary(
                market_id=market_id,
                first_trade_timestamp=ordered[0].timestamp,
                last_trade_timestamp=ordered[-1].timestamp,
                fill_count=len(ordered),
                total_buy_notional=total_buy_notional,
                total_sell_notional=total_sell_notional,
                ending_up_shares=final.up_inventory if final else ZERO,
                ending_down_shares=final.down_inventory if final else ZERO,
                max_paired_shares=max_paired,
                ending_paired_shares=final.paired_shares if final else ZERO,
                ending_directional_side=final.directional_side if final else None,
                ending_directional_shares=final.directional_shares if final else ZERO,
                weighted_avg_up_cost=final.up_weighted_avg_buy_cost if final else None,
                weighted_avg_down_cost=final.down_weighted_avg_buy_cost if final else None,
                weighted_pair_cost=pairing.weighted_pair_cost if pairing else None,
                weighted_gross_pair_edge=pairing.weighted_gross_pair_edge if pairing else None,
                fifo_pair_cost=pairing.fifo_pair_cost if pairing else None,
                fifo_gross_pair_edge=pairing.fifo_gross_pair_edge if pairing else None,
                history_complete=history_complete,
                validation_warnings=warnings,
            )
        )

    return sorted(summaries, key=lambda s: s.market_id)
