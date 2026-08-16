#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from polymarket_edge_lab.shadow.endurance_preflight import (
    DEFAULT_EVENT_COUNT,
    DEFAULT_MAX_GROWTH_RATIO,
    DEFAULT_MAX_LATE_MEDIAN_MS,
    DEFAULT_SAMPLE_WINDOW,
    run_event_store_endurance_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Disposable high-volume persistence endurance gate for Milestone 4A"
    )
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--event-count", type=int, default=DEFAULT_EVENT_COUNT)
    parser.add_argument("--sample-window", type=int, default=DEFAULT_SAMPLE_WINDOW)
    parser.add_argument("--max-growth-ratio", type=float, default=DEFAULT_MAX_GROWTH_RATIO)
    parser.add_argument(
        "--max-late-median-ms",
        type=float,
        default=DEFAULT_MAX_LATE_MEDIAN_MS,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = run_event_store_endurance_preflight(
        args.event_log,
        event_count=args.event_count,
        sample_window=args.sample_window,
        max_growth_ratio=args.max_growth_ratio,
        max_late_median_ms=args.max_late_median_ms,
    )
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output is not None:
        if args.output.resolve() == args.event_log.resolve():
            raise ValueError("preflight report output must not be the endurance event log")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    raise SystemExit(0 if report.ready else 1)


if __name__ == "__main__":
    main()
