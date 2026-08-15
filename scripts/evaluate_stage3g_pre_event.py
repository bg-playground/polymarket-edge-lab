#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from polymarket_edge_lab.analysis.stage3g_models import (
    MODEL_FEATURES,
    advancement_gate,
    evaluate_discovery,
    evaluate_external,
)


def _load(path: Path) -> list[dict[str, Any]]:
    return pq.read_table(path).to_pylist()


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate frozen Stage 3G pre-event models")
    parser.add_argument("--discovery-panel", type=Path, required=True)
    parser.add_argument("--external-panel", type=Path, required=True)
    parser.add_argument("--discovery-coverage", type=Path, required=True)
    parser.add_argument("--external-coverage", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    discovery = _load(args.discovery_panel)
    external = _load(args.external_panel)
    discovery_coverage = json.loads(args.discovery_coverage.read_text(encoding="utf-8"))
    external_coverage = json.loads(args.external_coverage.read_text(encoding="utf-8"))
    leakage_passed = bool(discovery_coverage["leakage_audit_passed"]) and bool(
        external_coverage["leakage_audit_passed"]
    )
    discovery_results = evaluate_discovery(discovery)
    external_results = evaluate_external(discovery, external)
    gate = advancement_gate(external_results, leakage_passed=leakage_passed)
    payload = {
        "discovery_row_count": len(discovery),
        "external_row_count": len(external),
        "discovery_window_count": len({row["window_id"] for row in discovery}),
        "external_window_count": len({row["window_id"] for row in external}),
        "model_features": {key: list(value) for key, value in MODEL_FEATURES.items()},
        "discovery_folds": discovery_results,
        "external_folds": external_results,
        "advancement_gate": gate,
        "leakage_audit_passed": leakage_passed,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "stage3g_pre_event_results.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(gate, indent=2))


if __name__ == "__main__":
    main()
