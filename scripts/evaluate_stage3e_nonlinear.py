from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from polymarket_edge_lab.analysis.stage3d_models import evaluate_held_out
from polymarket_edge_lab.analysis.stage3e_models import (
    evaluate_nonlinear_held_out,
    summarize_nonlinear_results,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Stage 3E nonlinear held-out benchmarks")
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = pq.read_table(args.panel).to_pylist()
    if not rows:
        raise SystemExit("Stage 3E panel is empty")

    stage3d_results = evaluate_held_out(rows)
    hurdle_folds = stage3d_results["timing_inventory"]
    nonlinear_folds = evaluate_nonlinear_held_out(rows)
    summary = summarize_nonlinear_results(nonlinear_folds, hurdle_folds)

    hurdle_summary = {
        "weighted_mae": sum(float(fold["weighted_mae"]) for fold in hurdle_folds)
        / len(hurdle_folds),
        "brier": sum(float(fold["brier"]) for fold in hurdle_folds) / len(hurdle_folds),
    }
    payload = {
        "row_count": len(rows),
        "window_count": len({str(row["window_id"]) for row in rows}),
        "interpretation": "held-out regime explanation; not a deployable trading prediction claim",
        "hurdle_model": "Stage 3D timing_inventory Ridge/logistic",
        "hurdle_folds": hurdle_folds,
        "hurdle_summary": hurdle_summary,
        "nonlinear_folds": nonlinear_folds,
        "summary": summary,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "stage3e_nonlinear_results.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    ordered = sorted(summary.items(), key=lambda item: float(item[1]["weighted_mae"]))
    lines = [
        "# Stage 3E constrained nonlinear held-out benchmark",
        "",
        f"Panel rows: **{len(rows)}**",
        f"Independent held-out windows: **{payload['window_count']}**",
        "",
        "## Frozen Stage 3D hurdle",
        "",
        f"- weighted MAE: **{hurdle_summary['weighted_mae']:.6f}**",
        f"- Brier: **{hurdle_summary['brier']:.6f}**",
        "",
        "## Nonlinear performance",
        "",
        (
            "| Model | weighted MAE | Δ MAE vs hurdle | MAE day wins | "
            "Brier | Δ Brier vs hurdle | Brier day wins |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, metrics in ordered:
        lines.append(
            f"| {name} | {float(metrics['weighted_mae']):.6f} | "
            f"{float(metrics['weighted_mae_delta_vs_hurdle']):+.6f} | "
            f"{int(metrics['mae_day_wins_vs_hurdle'])}/7 | "
            f"{float(metrics['brier']):.6f} | "
            f"{float(metrics['brier_delta_vs_hurdle']):+.6f} | "
            f"{int(metrics['brier_day_wins_vs_hurdle'])}/7 |"
        )

    primary = summary["hgb_timing_inventory"]
    gate_passed = bool(primary["advancement_gate_passed"])
    lines.extend(
        [
            "",
            "## Advancement gate",
            "",
            f"Primary HGB timing+inventory gate passed: **{gate_passed}**",
            "",
            (
                "The gate requires lower mean weighted MAE, lower mean Brier, and at least "
                "4/7 held-out-day wins on each metric versus the frozen Stage 3D hurdle."
            ),
            "",
            (
                "These are historical held-out explanatory results, not a live trading "
                "or future-profit claim."
            ),
        ]
    )
    report = "\n".join(lines) + "\n"
    (args.output_dir / "stage3e_nonlinear_results.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
