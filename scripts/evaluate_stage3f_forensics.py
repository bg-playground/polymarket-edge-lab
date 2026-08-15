from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from polymarket_edge_lab.analysis.stage3f_forensics import (
    discovery_ablation_results,
    external_validation,
    held_out_btc_permutation_results,
    summarize_ablation_results,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Stage 3F interaction forensics")
    parser.add_argument("--discovery-panel", type=Path, required=True)
    parser.add_argument("--external-panel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    discovery_rows: list[dict[str, Any]] = pq.read_table(args.discovery_panel).to_pylist()
    external_rows: list[dict[str, Any]] = pq.read_table(args.external_panel).to_pylist()
    if not discovery_rows or not external_rows:
        raise SystemExit("Stage 3F requires non-empty discovery and external panels")

    ablations = discovery_ablation_results(discovery_rows)
    ablation_summary = summarize_ablation_results(ablations)
    permutations = held_out_btc_permutation_results(discovery_rows)
    external = external_validation(discovery_rows, external_rows)

    payload = {
        "interpretation": "historical interaction forensics; not a deployable trading claim",
        "discovery_row_count": len(discovery_rows),
        "external_row_count": len(external_rows),
        "discovery_window_count": len({str(row["window_id"]) for row in discovery_rows}),
        "external_window_count": len({str(row["window_id"]) for row in external_rows}),
        "discovery_ablation_folds": ablations,
        "discovery_ablation_summary": ablation_summary,
        "btc_permutation_results": permutations,
        "external_validation": external,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "stage3f_forensics_results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    lines = [
        "# Stage 3F interaction forensics and external validation",
        "",
        f"Discovery rows: **{len(discovery_rows)}**",
        f"External rows: **{len(external_rows)}**",
        "",
        "## Discovery ablations",
        "",
        "| Model | weighted MAE | Δ vs T+I | Brier | Δ vs T+I |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metrics in sorted(
        ablation_summary.items(), key=lambda item: float(item[1]["weighted_mae"])
    ):
        lines.append(
            f"| {name} | {float(metrics['weighted_mae']):.6f} | "
            f"{float(metrics['weighted_mae_delta_vs_timing_inventory']):+.6f} | "
            f"{float(metrics['brier']):.6f} | "
            f"{float(metrics['brier_delta_vs_timing_inventory']):+.6f} |"
        )

    lines.extend(["", "## External July validation", ""])
    for name, metrics in external["summary"].items():
        lines.append(
            f"- {name}: weighted MAE **{float(metrics['weighted_mae']):.6f}**, "
            f"Brier **{float(metrics['brier']):.6f}**"
        )
    gate_passed = external["external_confirmation_gate_passed"]
    lines.extend(
        [
            "",
            f"MAE day wins vs HGB T+I: **{external['mae_day_wins_vs_hgb_timing_inventory']}/7**",
            (
                "Brier day wins vs HGB T+I: "
                f"**{external['brier_day_wins_vs_hgb_timing_inventory']}/7**"
            ),
            f"External confirmation gate passed: **{gate_passed}**",
            "",
            "These results are historical explanatory evidence, not a live trading recommendation.",
        ]
    )
    report = "\n".join(lines) + "\n"
    (args.output_dir / "stage3f_forensics_results.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
