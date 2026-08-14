#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from polymarket_edge_lab.analysis.bounded_pair_claim import (
    fully_contained_btc_5m_market_ids,
    summarize_chronological_pair_formation,
)
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger
from polymarket_edge_lab.storage.normalized import load_duckdb

TARGET_PAIR_COST = Decimal("0.9843")
TARGET_EDGE = Decimal("0.0157")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze chronological pair formation in a fully-contained BTC 5m cohort"
    )
    parser.add_argument("--account", required=True)
    parser.add_argument("--duckdb-path", type=Path, required=True)
    parser.add_argument("--collection-start", type=int, required=True)
    parser.add_argument("--collection-end", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/bounded-claim-grade"))
    args = parser.parse_args()

    trades = load_duckdb(args.duckdb_path, account=args.account)
    if not trades:
        raise SystemExit("No trades available for bounded pair-claim analysis")

    complete_market_ids = fully_contained_btc_5m_market_ids(
        trades,
        collection_start=args.collection_start,
        collection_end=args.collection_end,
    )
    ledger = build_canonical_ledger(trades, complete_market_ids=complete_market_ids)

    canonical, events = summarize_chronological_pair_formation(
        ledger,
        complete_market_ids=complete_market_ids,
        tie_break="canonical",
    )
    price_asc, _ = summarize_chronological_pair_formation(
        ledger,
        complete_market_ids=complete_market_ids,
        tie_break="price_asc",
    )
    price_desc, _ = summarize_chronological_pair_formation(
        ledger,
        complete_market_ids=complete_market_ids,
        tie_break="price_desc",
    )

    observed_cost = canonical.weighted_pair_cost
    observed_edge = canonical.weighted_gross_pair_edge
    status = "inconclusive"
    if observed_cost is not None:
        status = (
            "supported_in_bounded_cohort"
            if abs(observed_cost - TARGET_PAIR_COST) <= Decimal("0.005")
            else "not_supported_in_bounded_cohort"
        )

    payload = {
        "account": args.account,
        "collection_start": args.collection_start,
        "collection_end": args.collection_end,
        "cohort_definition": (
            "Observed btc-updown-5m-<epoch> markets whose full [start,start+300) "
            "interval lies inside the collection interval"
        ),
        "complete_market_ids": sorted(complete_market_ids),
        "canonical": {k: _json_value(v) for k, v in asdict(canonical).items()},
        "within_second_ordering_sensitivity": {
            "price_asc_weighted_pair_cost": _json_value(price_asc.weighted_pair_cost),
            "price_desc_weighted_pair_cost": _json_value(price_desc.weighted_pair_cost),
        },
        "public_claim": {
            "target_pair_cost": str(TARGET_PAIR_COST),
            "target_gross_edge": str(TARGET_EDGE),
            "status": status,
        },
        "limitations": [
            "This is a bounded cohort, not the trader's full history.",
            "Public API timestamps have one-second resolution; sub-second ordering is unknown.",
            "Markets containing SELL fills are excluded from this BUY-lot pairing method.",
            (
                "Pair costs are gross execution-price sums and do not include fees or "
                "settlement effects."
            ),
        ],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "bounded_pair_claim.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    event_rows = [{k: _json_value(v) for k, v in asdict(event).items()} for event in events]
    (args.output_dir / "pair_formation_events.json").write_text(
        json.dumps(event_rows, indent=2), encoding="utf-8"
    )

    def cents(value: Decimal | None) -> str:
        return "n/a" if value is None else f"{value * Decimal('100'):.4f}¢"

    lines = [
        "# Bounded claim-grade BTC 5-minute pair-formation analysis",
        "",
        f"Account: `{args.account}`",
        f"Collection interval: `[{args.collection_start}, {args.collection_end})`",
        "",
        "## Cohort",
        "",
        f"- Fully contained observed BTC 5-minute markets: **{canonical.market_count}**",
        f"- Included fills: **{canonical.fill_count}**",
        f"- Pair-match fragments: **{canonical.pair_fragment_count}**",
        f"- Formed pair quantity: **{canonical.paired_shares}** shares",
        (
            "- Markets excluded because SELL fills were present: "
            f"**{len(canonical.excluded_sell_markets)}**"
        ),
        "",
        "## Chronological pair-formation result",
        "",
        f"- Quantity-weighted pair cost: **{cents(observed_cost)}**",
        f"- Implied gross paired edge: **{cents(observed_edge)}**",
        f"- Pair quantity formed below $1.00: **{canonical.below_one_ratio}**",
        f"- Pair quantity formed with zero-second observed lag: **{canonical.zero_lag_ratio}**",
        "",
        "## Within-second ordering sensitivity",
        "",
        f"- Price-ascending tie order: **{cents(price_asc.weighted_pair_cost)}**",
        f"- Price-descending tie order: **{cents(price_desc.weighted_pair_cost)}**",
        "",
        "## X-post comparison",
        "",
        "- Claimed average pair cost: **98.4300¢**",
        "- Claimed gross paired edge: **1.5700¢**",
        f"- Bounded-cohort status: **{status}**",
        "",
        (
            "This status applies only to this fully-contained bounded cohort; "
            "it is not a full-history verdict."
        ),
        "",
        "## Limitations",
        "",
        (
            "- Public timestamps have one-second resolution, so exact sub-second fill "
            "ordering is unavailable."
        ),
        (
            "- This pairing method matches newly purchased shares FIFO against previously "
            "unmatched complementary BUY lots."
        ),
        (
            "- Markets with SELL fills are excluded rather than forcing a more speculative "
            "lot-accounting rule."
        ),
        "- Fees and settlement effects are not included in the gross execution-price pair cost.",
    ]
    (args.output_dir / "bounded_pair_claim.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
