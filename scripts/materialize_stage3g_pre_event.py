#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from polymarket_edge_lab.analysis.stage3g_panel import (
    materialize_pre_event_window,
    write_pre_event_panel,
)
from polymarket_edge_lab.data.btc_reference import load_coinbase_candles


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize strict Stage 3G pre-event panel")
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
        rows, diag = materialize_pre_event_window(
            window_id=window_id,
            account=args.account,
            duckdb_path=args.data_root / window_id / "window.duckdb",
            collection_start=int(window["start_epoch"]),
            collection_end=int(window["end_epoch"]),
            btc_candles=candles,
        )
        all_rows.extend(rows)
        diagnostics.append(diag)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_pre_event_panel(args.output_dir / "stage3g_pre_event_panel.parquet", all_rows)
    audit_passed = all(bool(item["leakage_audit"]["passed"]) for item in diagnostics)
    report = {
        "windows": diagnostics,
        "panel_row_count": len(all_rows),
        "leakage_audit_passed": audit_passed,
    }
    (args.output_dir / "stage3g_pre_event_coverage.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if not audit_passed:
        raise SystemExit("strict pre-event leakage audit failed")
    print(f"materialized {len(all_rows)} strict pre-event rows across {len(diagnostics)} windows")


if __name__ == "__main__":
    main()
