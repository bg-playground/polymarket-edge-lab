#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from polymarket_edge_lab.shadow.bounded_replay import audit_bounded_shadow_replay
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit a bounded Milestone 4A event log without external APIs"
    )
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--numeric-tolerance", type=float, default=1e-12)
    args = parser.parse_args()

    result = audit_bounded_shadow_replay(
        AppendOnlyEventStore(args.event_log),
        artifact_dir=args.artifact_dir,
        numeric_tolerance=args.numeric_tolerance,
    )
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
