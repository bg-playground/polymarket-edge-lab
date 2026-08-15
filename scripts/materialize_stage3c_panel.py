#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from polymarket_edge_lab.analysis.stage3c_panel import materialize_window, write_panel_parquet
from polymarket_edge_lab.data.btc_reference import load_coinbase_candles


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize Stage 3C research feature panel")
    parser.add_argument("--account", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--btc-raw", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    candles = load_coinbase_candles(args.btc_raw, interval_seconds=60)
    all_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for window in manifest["windows"]:
        window_id = str(window["window_id"])
        rows, window_diag = materialize_window(
            window_id=window_id,
            account=args.account,
            duckdb_path=args.data_root / window_id / "window.duckdb",
            collection_start=int(window["start_epoch"]),
            collection_end=int(window["end_epoch"]),
            btc_candles=candles,
        )
        all_rows.extend(rows)
        diagnostics.append(window_diag)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_panel_parquet(args.output_dir / "stage3c_feature_panel.parquet", all_rows)
    _write_csv(args.output_dir / "stage3c_feature_panel_sample.csv", all_rows[:500])
    (args.output_dir / "stage3c_coverage.json").write_text(
        json.dumps({"windows": diagnostics, "panel_row_count": len(all_rows)}, indent=2),
        encoding="utf-8",
    )
    print(f"materialized {len(all_rows)} event rows across {len(diagnostics)} windows")
    for row in diagnostics:
        print(
            row["window_id"],
            f"rows={row['panel_row_count']}",
            f"markets={row['complete_market_count']}",
            f"sell_excluded={row['sell_excluded_market_count']}",
        )


if __name__ == "__main__":
    main()
