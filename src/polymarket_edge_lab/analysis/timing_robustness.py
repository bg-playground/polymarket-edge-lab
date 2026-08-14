from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ZERO = Decimal("0")
ONE = Decimal("1")
ADEQUATE_SHARES = Decimal("500")
Classification = Literal["replicated", "mixed", "not_replicated", "insufficient_data"]


@dataclass(frozen=True)
class WindowMetric:
    window_id: str
    start_epoch: int
    end_epoch: int
    complete: bool
    paired_shares: Decimal
    weighted_pair_cost: Decimal | None
    below_one_ratio: Decimal | None


def weighted_cost(rows: list[WindowMetric]) -> Decimal | None:
    usable = [
        row
        for row in rows
        if row.complete and row.weighted_pair_cost is not None and row.paired_shares > ZERO
    ]
    quantity = sum((row.paired_shares for row in usable), start=ZERO)
    if quantity == ZERO:
        return None
    cost = sum(
        (row.weighted_pair_cost * row.paired_shares for row in usable),  # type: ignore[operator]
        start=ZERO,
    )
    return cost / quantity


def equal_window_mean(rows: list[WindowMetric]) -> Decimal | None:
    costs = [
        row.weighted_pair_cost
        for row in rows
        if row.complete
        and row.paired_shares >= ADEQUATE_SHARES
        and row.weighted_pair_cost is not None
    ]
    if not costs:
        return None
    return sum(costs, start=ZERO) / Decimal(len(costs))


def leave_one_out(rows: list[WindowMetric]) -> list[dict[str, object]]:
    ordered = sorted(rows, key=lambda row: (row.start_epoch, row.window_id))
    return [
        {
            "omitted_window": row.window_id,
            "pooled_pair_cost": weighted_cost([other for other in ordered if other != row]),
        }
        for row in ordered
    ]


def cumulative(rows: list[WindowMetric]) -> list[dict[str, object]]:
    ordered = sorted(rows, key=lambda row: (row.start_epoch, row.window_id))
    return [
        {
            "through_window": row.window_id,
            "window_count": index,
            "pooled_pair_cost": weighted_cost(ordered[:index]),
        }
        for index, row in enumerate(ordered, start=1)
    ]


def classify(rows: list[WindowMetric]) -> Classification:
    adequate = [
        row
        for row in rows
        if row.complete
        and row.paired_shares >= ADEQUATE_SHARES
        and row.weighted_pair_cost is not None
    ]
    if len(adequate) < 4 or any(not row.complete for row in rows):
        return "insufficient_data"
    pooled = weighted_cost(adequate)
    if pooled is None:
        return "insufficient_data"
    if pooled >= ONE:
        return "not_replicated"
    below = sum(1 for row in adequate if row.weighted_pair_cost is not None and row.weighted_pair_cost < ONE)
    fraction = Decimal(below) / Decimal(len(adequate))
    loo = leave_one_out(adequate)
    loo_below = all(
        item["pooled_pair_cost"] is not None and item["pooled_pair_cost"] < ONE  # type: ignore[operator]
        for item in loo
    )
    if fraction >= Decimal("0.60") and loo_below:
        return "replicated"
    return "mixed"


def summarize_hypothesis(rows: list[WindowMetric]) -> dict[str, object]:
    adequate = [
        row
        for row in rows
        if row.complete
        and row.paired_shares >= ADEQUATE_SHARES
        and row.weighted_pair_cost is not None
    ]
    costs = sorted(row.weighted_pair_cost for row in adequate if row.weighted_pair_cost is not None)
    below_count = sum(1 for cost in costs if cost < ONE)
    total_quantity = sum((row.paired_shares for row in adequate), start=ZERO)

    def percentile(p: Decimal) -> Decimal | None:
        if not costs:
            return None
        index = int((Decimal(len(costs) - 1) * p).to_integral_value(rounding="ROUND_HALF_UP"))
        return costs[index]

    concentration = [
        {
            "window_id": row.window_id,
            "paired_shares": row.paired_shares,
            "share_of_adequate_quantity": (
                row.paired_shares / total_quantity if total_quantity > ZERO else None
            ),
        }
        for row in adequate
    ]
    return {
        "classification": classify(rows),
        "requested_window_count": len(rows),
        "complete_window_count": sum(1 for row in rows if row.complete),
        "adequate_window_count": len(adequate),
        "pooled_pair_cost": weighted_cost(adequate),
        "equal_window_mean_pair_cost": equal_window_mean(adequate),
        "median_window_pair_cost": percentile(Decimal("0.50")),
        "p25_window_pair_cost": percentile(Decimal("0.25")),
        "p75_window_pair_cost": percentile(Decimal("0.75")),
        "min_window_pair_cost": costs[0] if costs else None,
        "max_window_pair_cost": costs[-1] if costs else None,
        "windows_below_one": below_count,
        "fraction_adequate_windows_below_one": (
            Decimal(below_count) / Decimal(len(adequate)) if adequate else None
        ),
        "paired_quantity_concentration": concentration,
        "leave_one_window_out": leave_one_out(adequate),
        "cumulative_chronological": cumulative(adequate),
    }
