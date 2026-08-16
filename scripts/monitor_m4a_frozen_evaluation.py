#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymarket_edge_lab.shadow.operational_monitor import (
    inspect_frozen_evaluation_log,
    render_operational_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only operational monitor for a frozen Milestone 4A event log"
    )
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--output",
        type=Path,
        help="optionally write the JSON report to a separate monitor file",
    )
    args = parser.parse_args()

    report = inspect_frozen_evaluation_log(args.event_log)
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)

    if args.output is not None:
        if args.output.resolve() == args.event_log.resolve():
            raise ValueError("monitor output must not be the evaluation event log")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    print(payload if args.json else render_operational_summary(report))


if __name__ == "__main__":
    main()
