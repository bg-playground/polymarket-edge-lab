from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from polymarket_edge_lab.analysis.trading_activity import TradingActivitySummary
from polymarket_edge_lab.models.reconstruction import ExposureSummary, MarketSummary


@dataclass(frozen=True)
class ClaimResult:
    claim: str
    measured_value: str
    methodology: str
    sample_size: str
    caveats: str
    status: str


def _status_from_target(measured: Decimal | None, target: Decimal, tolerance: Decimal) -> str:
    if measured is None:
        return "inconclusive"
    return "supported" if abs(measured - target) <= tolerance else "not_supported"


def build_claim_results(
    *,
    activity: TradingActivitySummary,
    exposure: ExposureSummary,
    market_summaries: list[MarketSummary],
) -> list[ClaimResult]:
    complete_markets = [m for m in market_summaries if m.history_complete]
    pair_cost_markets = [
        m
        for m in complete_markets
        if m.weighted_pair_cost is not None and m.ending_paired_shares > Decimal("0")
    ]

    avg_pair_cost = None
    total_paired_shares = sum(
        (m.ending_paired_shares for m in pair_cost_markets),
        start=Decimal("0"),
    )
    if pair_cost_markets and total_paired_shares > Decimal("0"):
        weighted_total_cost = sum(
            (
                m.weighted_pair_cost * m.ending_paired_shares
                for m in pair_cost_markets
                if m.weighted_pair_cost is not None
            ),
            start=Decimal("0"),
        )
        avg_pair_cost = weighted_total_cost / total_paired_shares

    avg_pair_edge = None
    if avg_pair_cost is not None:
        avg_pair_edge = Decimal("1") - avg_pair_cost

    unweighted_avg_pair_cost = None
    if pair_cost_markets:
        costs = [
            m.weighted_pair_cost for m in pair_cost_markets if m.weighted_pair_cost is not None
        ]
        if costs:
            unweighted_avg_pair_cost = sum(costs, start=Decimal("0")) / Decimal(len(costs))

    paired_ratio = exposure.paired_share_event_ratio
    directional_ratio = exposure.directional_share_event_ratio

    return [
        ClaimResult(
            claim="51.25 trades / active hour",
            measured_value=str(activity.trades_per_active_hour),
            methodology="total_trades / distinct UTC active-hour buckets",
            sample_size=str(activity.total_trades),
            caveats="depends on public-history completeness",
            status=_status_from_target(
                activity.trades_per_active_hour, Decimal("51.25"), Decimal("0.25")
            ),
        ),
        ClaimResult(
            claim="$110.67 average trade",
            measured_value=str(activity.average_trade_notional),
            methodology="mean absolute fill notional",
            sample_size=str(activity.total_trades),
            caveats="public fills only",
            status=_status_from_target(
                activity.average_trade_notional, Decimal("110.67"), Decimal("1.0")
            ),
        ),
        ClaimResult(
            claim="50% win rate",
            measured_value="undefined",
            methodology="win-rate definition unavailable from public context",
            sample_size="0",
            caveats="metric ambiguous; not inferred",
            status="inconclusive",
        ),
        ClaimResult(
            claim="98.43¢ average pair cost",
            measured_value=str(avg_pair_cost),
            methodology=(
                "pair-quantity-weighted mean weighted-average "
                "pair cost over complete eligible markets"
            ),
            sample_size=str(total_paired_shares),
            caveats=(
                "excludes incomplete-history markets; "
                f"secondary unweighted market mean={unweighted_avg_pair_cost} across "
                f"{len(pair_cost_markets)} markets"
            ),
            status=_status_from_target(avg_pair_cost, Decimal("0.9843"), Decimal("0.005")),
        ),
        ClaimResult(
            claim="1.57¢ gross paired edge",
            measured_value=str(avg_pair_edge),
            methodology=(
                "1 - pair-quantity-weighted mean weighted-average "
                "pair cost over complete eligible markets"
            ),
            sample_size=str(total_paired_shares),
            caveats="excludes incomplete-history markets",
            status=_status_from_target(avg_pair_edge, Decimal("0.0157"), Decimal("0.005")),
        ),
        ClaimResult(
            claim="78.7% paired inventory",
            measured_value=str(paired_ratio),
            methodology="event/share-weighted paired ratio",
            sample_size=str(activity.total_trades),
            caveats="definition-sensitive; other definitions also reported",
            status=_status_from_target(paired_ratio, Decimal("0.787"), Decimal("0.05")),
        ),
        ClaimResult(
            claim="21.3% directional residual",
            measured_value=str(directional_ratio),
            methodology="event/share-weighted directional ratio",
            sample_size=str(activity.total_trades),
            caveats="definition-sensitive; other definitions also reported",
            status=_status_from_target(directional_ratio, Decimal("0.213"), Decimal("0.05")),
        ),
        ClaimResult(
            claim="+$126,836 total P&L",
            measured_value="unavailable",
            methodology="requires settlement/payout enrichment not in Milestone 2 base pipeline",
            sample_size="0",
            caveats="public trade history alone is insufficient",
            status="inconclusive",
        ),
    ]


def claim_results_to_json(results: list[ClaimResult]) -> list[dict[str, str]]:
    return [asdict(r) for r in results]


def claim_results_to_markdown(results: list[ClaimResult]) -> str:
    header = "| Public claim | Measured result | Method | Sample size | Caveats | Status |"
    sep = "|---|---|---|---|---|---|"
    rows = [
        "| "
        f"{r.claim} | {r.measured_value} | {r.methodology} | "
        f"{r.sample_size} | {r.caveats} | {r.status} |"
        for r in results
    ]
    return "\n".join([header, sep, *rows]) + "\n"
