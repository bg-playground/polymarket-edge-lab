#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow.parquet as pq

from polymarket_edge_lab.models.stage3g_frozen import fit_and_write_frozen_models


def main() -> None:
    parser = argparse.ArgumentParser(description="Export frozen Stage 3G models for Milestone 4A")
    parser.add_argument("--discovery-panel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()

    rows = pq.read_table(args.discovery_panel).to_pylist()
    metadata = fit_and_write_frozen_models(
        rows,
        output_dir=args.output_dir,
        source_commit=args.source_commit,
    )
    print(f"exported {len(metadata)} frozen Stage 3G model pairs to {args.output_dir}")
    for item in metadata:
        print(
            f"{item.model_name}: rows={item.training_row_count} "
            f"weight={item.training_paired_share_weight:.6f} "
            f"reg={item.regressor_sha256[:12]} cls={item.classifier_sha256[:12]}"
        )


if __name__ == "__main__":
    main()
