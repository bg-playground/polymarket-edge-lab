from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from polymarket_edge_lab.analysis.stage3d_models import evaluate_held_out, summarize_results


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Stage 3D held-out explanatory baselines")
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = pq.read_table(args.panel).to_pylist()
    if not rows:
        raise SystemExit("Stage 3D panel is empty")
    results = evaluate_held_out(rows)
    summary = summarize_results(results)
    payload = {
        "row_count": len(rows),
        "window_count": len({str(row["window_id"]) for row in rows}),
        "interpretation": "held-out regime explanation; not a deployable trading prediction claim",
        "primary_feature_policy": (
            "inventory price/VWAP fields are excluded from primary models because they include "
            "the pair-forming execution itself"
        ),
        "folds": results,
        "summary": summary,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "stage3d_heldout_results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    ordered = sorted(summary.items(), key=lambda item: item[1]["weighted_mae"])
    lines = [
        "# Stage 3D held-out explanatory baselines",
        "",
        f"Panel rows: **{len(rows)}**",
        f"Independent held-out windows: **{payload['window_count']}**",
        "",
        "## Mean performance across held-out days",
        "",
        "| Model | weighted MAE | Δ MAE vs timing | Brier | Δ Brier vs timing |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, metrics in ordered:
        lines.append(
            f"| {name} | {metrics['weighted_mae']:.6f} | "
            f"{metrics['weighted_mae_delta_vs_timing']:+.6f} | "
            f"{metrics['brier']:.6f} | {metrics['brier_delta_vs_timing']:+.6f} |"
        )
    lines.extend(
        [
            "",
            "Negative deltas versus timing indicate improvement.",
            "",
            "These are historical held-out explanatory results, not a live trading or future-profit claim.",
        ]
    )
    (args.output_dir / "stage3d_heldout_results.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
