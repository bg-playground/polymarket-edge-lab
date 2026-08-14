from __future__ import annotations

from decimal import Decimal

from polymarket_edge_lab.models.reconstruction import ExposureSummary, InventoryEvent

ZERO = Decimal("0")


def summarize_exposure(events: list[InventoryEvent]) -> ExposureSummary:
    if not events:
        return ExposureSummary(None, None, None, None, None, None)

    paired_weight = ZERO
    directional_weight = ZERO
    event_weight_total = ZERO

    for event in events:
        weight = event.shares
        total = event.paired_shares + event.directional_shares
        if total <= ZERO:
            continue
        event_weight_total += weight
        paired_weight += weight * (event.paired_shares / total)
        directional_weight += weight * (event.directional_shares / total)

    paired_share_event_ratio = (
        paired_weight / event_weight_total if event_weight_total > ZERO else None
    )
    directional_share_event_ratio = (
        directional_weight / event_weight_total if event_weight_total > ZERO else None
    )

    final = events[-1]
    final_total = final.paired_shares + final.directional_shares
    paired_end_ratio = final.paired_shares / final_total if final_total > ZERO else None
    directional_end_ratio = final.directional_shares / final_total if final_total > ZERO else None

    paired_cost = final.paired_shares * (
        (final.up_weighted_avg_buy_cost or ZERO) + (final.down_weighted_avg_buy_cost or ZERO)
    )
    directional_cost = ZERO
    if final.directional_side == "UP":
        directional_cost = final.directional_shares * (final.up_weighted_avg_buy_cost or ZERO)
    elif final.directional_side == "DOWN":
        directional_cost = final.directional_shares * (final.down_weighted_avg_buy_cost or ZERO)

    total_cost = paired_cost + directional_cost
    paired_dollar_ratio = paired_cost / total_cost if total_cost > ZERO else None
    directional_dollar_ratio = directional_cost / total_cost if total_cost > ZERO else None

    return ExposureSummary(
        paired_share_event_ratio=paired_share_event_ratio,
        directional_share_event_ratio=directional_share_event_ratio,
        paired_end_of_market_ratio=paired_end_ratio,
        directional_end_of_market_ratio=directional_end_ratio,
        paired_dollar_cost_ratio=paired_dollar_ratio,
        directional_dollar_cost_ratio=directional_dollar_ratio,
    )
