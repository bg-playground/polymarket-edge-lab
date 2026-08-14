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

from polymarket_edge_lab.analysis.bounded_pair_claim import fully_contained_btc_5m_market_ids
from polymarket_edge_lab.analysis.pair_sensitivity import (
    distribution,
    latency_metrics,
    market_time_metrics,
    pair_events_by_method,
    per_market_metrics,
    summarize_events,
    transaction_hash_diagnostic,
)
from polymarket_edge_lab.reconstruction.ledger import build_canonical_ledger
from polymarket_edge_lab.storage.normalized import load_duckdb

TARGET = Decimal("0.9843")


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _cents(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value * Decimal('100'):.4f}c"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded empirical pair sensitivity and latency analysis")
    parser.add_argument("--account", required=True)
    parser.add_argument("--duckdb-path", type=Path, required=True)
    parser.add_argument("--collection-start", type=int, required=True)
    parser.add_argument("--collection-end", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/pair-sensitivity"))
    args = parser.parse_args()

    trades = load_duckdb(args.duckdb_path, account=args.account)
    if not trades:
        raise SystemExit("No trades available")
    complete_ids = fully_contained_btc_5m_market_ids(
        trades, collection_start=args.collection_start, collection_end=args.collection_end
    )
    ledger = build_canonical_ledger(trades, complete_market_ids=complete_ids)
    events_by_method, sell_markets = pair_events_by_method(ledger, complete_market_ids=complete_ids)
    summaries = {method: summarize_events(method, events) for method, events in events_by_method.items()}
    market_rows = per_market_metrics(events_by_method)

    fifo_events = events_by_method["fifo"]
    latency = latency_metrics(fifo_events)
    time_buckets, time_bands = market_time_metrics(fifo_events)
    tx_diag = transaction_hash_diagnostic(ledger, complete_ids)

    market_costs: dict[str, dict[str, object]] = {}
    for method in events_by_method:
        values: list[Decimal] = []
        for row in market_rows:
            method_row = row[method]
            if isinstance(method_row, dict):
                value = method_row.get("weighted_pair_cost")
                if isinstance(value, Decimal):
                    values.append(value)
        market_costs[method] = distribution(values)

    method_comparison = {method: asdict(summary) for method, summary in summaries.items()}
    claim_distance = {
        method: (
            abs(summary.weighted_pair_cost - TARGET)
            if summary.weighted_pair_cost is not None
            else None
        )
        for method, summary in summaries.items()
    }
    full_cohort_near_claim = any(
        distance is not None and distance <= Decimal("0.005") for distance in claim_distance.values()
    )

    payload = {
        "account": args.account,
        "collection_start": args.collection_start,
        "collection_end": args.collection_end,
        "eligible_market_count": len(complete_ids),
        "excluded_sell_markets": list(sell_markets),
        "accounting_methods": method_comparison,
        "market_cost_distributions": market_costs,
        "latency_buckets_fifo": latency,
        "time_within_market_buckets_fifo": time_buckets,
        "time_within_market_bands_fifo": time_bands,
        "transaction_hash_diagnostic": tx_diag,
        "public_claim": {
            "pair_cost": TARGET,
            "gross_edge": Decimal("0.0157"),
            "distance_by_method": claim_distance,
            "any_standard_full_cohort_method_near_claim": full_cohort_near_claim,
        },
        "interpretation_guardrails": [
            "FIFO is the primary chronological lot-matching baseline; LIFO is sensitivity only.",
            "Weighted-average accounting uses only inventory and cost known at each pair increase.",
            "Latency and market-time buckets are descriptive slices, not alternative full-cohort claims.",
            "Same-transaction-hash pairing is diagnostic and does not imply one hash equals one order.",
            "No strategy intent, net profitability, or predictive signal is inferred.",
        ],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "pair_sensitivity.json").write_text(json.dumps(_json(payload), indent=2), encoding="utf-8")
    (args.output_dir / "per_market_metrics.json").write_text(json.dumps(_json(market_rows), indent=2), encoding="utf-8")
    event_payload = {
        method: [asdict(event) for event in events] for method, events in events_by_method.items()
    }
    (args.output_dir / "pair_events_by_method.json").write_text(
        json.dumps(_json(event_payload), indent=2), encoding="utf-8"
    )

    fifo = summaries["fifo"]
    lifo = summaries["lifo"]
    wav = summaries["weighted_average"]
    profitable_latency = [
        row for row in latency if isinstance(row.get("weighted_pair_cost"), Decimal) and row["weighted_pair_cost"] < Decimal("1")
    ]
    profitable_time = [
        row for row in time_buckets if isinstance(row.get("weighted_pair_cost"), Decimal) and row["weighted_pair_cost"] < Decimal("1")
    ]
    lines = [
        "# Empirical pair sensitivity and latency analysis",
        "",
        f"Eligible fully-contained BTC 5m markets: **{len(complete_ids)}**",
        f"SELL-excluded markets: **{len(sell_markets)}**",
        "",
        "## Full-cohort accounting definitions",
        "",
        f"- FIFO: **{_cents(fifo.weighted_pair_cost)}**, edge **{_cents(fifo.gross_edge)}**, below-$1 share **{fifo.below_one_ratio}**",
        f"- LIFO sensitivity: **{_cents(lifo.weighted_pair_cost)}**, edge **{_cents(lifo.gross_edge)}**, below-$1 share **{lifo.below_one_ratio}**",
        f"- Incremental weighted average: **{_cents(wav.weighted_pair_cost)}**, edge **{_cents(wav.gross_edge)}**, below-$1 share **{wav.below_one_ratio}**",
        "",
        "## Public 98.43c claim",
        "",
        f"Any standard full-cohort method within 0.5c of 98.43c: **{full_cohort_near_claim}**",
        "",
        "## FIFO profitable concentration diagnostics",
        "",
        f"Latency buckets with weighted pair cost below $1: **{', '.join(str(r['bucket']) for r in profitable_latency) or 'none'}**",
        f"30-second market-time buckets below $1: **{', '.join(str(r['bucket']) for r in profitable_time) or 'none'}**",
        "",
        "Detailed bucket, per-market, transaction-hash, and event-level results are in the JSON outputs.",
        "",
        "This report is bounded-cohort execution-price accounting only; it is not a full-history profitability or strategy verdict.",
    ]
    (args.output_dir / "pair_sensitivity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
