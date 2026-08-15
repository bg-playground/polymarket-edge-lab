#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from polymarket_edge_lab.shadow.reporting import build_prospective_report, json_dumps
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the deterministic Milestone 4A prospective evaluation report"
    )
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_prospective_report(
        AppendOnlyEventStore(args.event_log),
        generated_at=datetime.now(tz=UTC),
    )
    rendered = json_dumps(report) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
