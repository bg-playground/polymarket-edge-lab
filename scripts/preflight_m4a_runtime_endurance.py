#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from polymarket_edge_lab.shadow.runtime_endurance import (
    DEFAULT_CYCLE_COUNT,
    DEFAULT_EVENT_COUNT,
    DEFAULT_MAX_CYCLE_MS,
    DEFAULT_MAX_P95_CYCLE_MS,
    json_dumps,
    run_runtime_endurance_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the disposable M4A integrated large-log runtime endurance gate"
    )
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--event-count", type=int, default=DEFAULT_EVENT_COUNT)
    parser.add_argument("--cycle-count", type=int, default=DEFAULT_CYCLE_COUNT)
    parser.add_argument("--max-p95-cycle-ms", type=float, default=DEFAULT_MAX_P95_CYCLE_MS)
    parser.add_argument("--max-cycle-ms", type=float, default=DEFAULT_MAX_CYCLE_MS)
    args = parser.parse_args()

    report = run_runtime_endurance_preflight(
        event_log=args.event_log,
        event_count=args.event_count,
        cycle_count=args.cycle_count,
        max_p95_cycle_ms=args.max_p95_cycle_ms,
        max_cycle_ms=args.max_cycle_ms,
    )
    rendered = json_dumps(report)
    print(rendered)
    if args.output is not None:
        if args.output.resolve() == args.event_log.resolve():
            raise ValueError("output path must differ from the disposable event log")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not report.ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
