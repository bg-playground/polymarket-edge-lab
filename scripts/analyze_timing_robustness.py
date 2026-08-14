#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from polymarket_edge_lab.analysis.timing_robustness import WindowMetric, summarize_hypothesis

PRIMARY_LATENCY = "61-120s"
PRIMARY_MARKET_TIME = "middle_100_199"


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _find_bucket(rows: list[dict[str, object]], bucket: str) -> dict[str, object] | None:
    return next((row for row in rows if row.get("bucket") == bucket), None)


def _metric(
    *,
    window: dict[str, object],
    row: dict[str, object] | None,
) -> WindowMetric:
    return WindowMetric(
        window_id=str(window["window_id"]),
        start_epoch=int(window["start_epoch"]),
        end_epoch=int(window["end_epoch"]),
        complete=bool(window["complete"]),
        paired_shares=_decimal(row.get("paired_shares") if row else None) or Decimal("0"),
        weighted_pair_cost=_decimal(row.get("weighted_pair_cost") if row else None),
        below_one_ratio=_decimal(row.get("below_one_ratio") if row else None),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate independent timing-robustness windows")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    latency_metrics: list[WindowMetric] = []
    market_time_metrics: list[WindowMetric] = []
    windows_out: list[dict[str, object]] = []

    for window in manifest["windows"]:
        report_path = args.reports_root / str(window["window_id"]) / "pair_sensitivity.json"
        complete = bool(window.get("complete", False)) and report_path.exists()
        window = {**window, "complete": complete}
        report = json.loads(report_path.read_text(encoding="utf-8")) if complete else None
        latency_row = (
            _find_bucket(report["latency_buckets_fifo"], PRIMARY_LATENCY) if report else None
        )
        market_time_row = (
            _find_bucket(report["time_within_market_bands_fifo"], PRIMARY_MARKET_TIME)
            if report
            else None
        )
        latency_metrics.append(_metric(window=window, row=latency_row))
        market_time_metrics.append(_metric(window=window, row=market_time_row))
        windows_out.append(
            {
                **window,
                "eligible_market_count": report.get("eligible_market_count") if report else None,
                "fifo_full_cohort": (report["accounting_methods"].get("fifo") if report else None),
                "primary_latency": latency_row,
                "primary_market_time": market_time_row,
            }
        )

    latency_summary = summarize_hypothesis(latency_metrics)
    market_time_summary = summarize_hypothesis(market_time_metrics)
    payload = {
        "design": {
            "primary_latency_bucket": PRIMARY_LATENCY,
            "primary_market_time_band": PRIMARY_MARKET_TIME,
            "adequate_window_min_paired_shares": "500",
            "classification_rule": (
                "replicated requires pooled cost <1, >=60% of adequate windows <1, "
                "and every leave-one-window-out pooled estimate <1"
            ),
        },
        "windows": windows_out,
        "primary_hypotheses": {
            "latency_61_120s": latency_summary,
            "market_time_100_199s": market_time_summary,
        },
        "guardrails": [
            "Primary hypotheses and bucket boundaries were frozen before expanded collection.",
            "Secondary buckets are descriptive and are not promoted by this report.",
            "Classifications describe historical execution-price accounting only.",
            "No predictive, backtest, or future-profitability claim is made.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "timing_robustness.json").write_text(
        json.dumps(_json(payload), indent=2), encoding="utf-8"
    )
    lines = [
        "# Empirical timing robustness",
        "",
        f"Requested independent windows: **{len(windows_out)}**",
        "",
        "## Predeclared primary hypotheses",
        "",
        f"- 61-120s latency: **{latency_summary['classification']}**, "
        f"pooled cost **{latency_summary['pooled_pair_cost']}**",
        f"- market seconds 100-199: **{market_time_summary['classification']}**, "
        f"pooled cost **{market_time_summary['pooled_pair_cost']}**",
        "",
        "See timing_robustness.json for per-window, leave-one-out, cumulative, and "
        "quantity-concentration evidence.",
    ]
    (args.output_dir / "timing_robustness.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
