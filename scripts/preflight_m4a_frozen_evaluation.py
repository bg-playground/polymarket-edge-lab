#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from polymarket_edge_lab.shadow.preflight import json_dumps, run_frozen_evaluation_preflight


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Milestone 4A frozen-evaluation launch readiness without starting the real run"
        )
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repository-commit", required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = asyncio.run(
        run_frozen_evaluation_preflight(
            run_id=args.run_id,
            repository_commit=args.repository_commit,
            repository_root=args.repository_root,
            artifact_dir=args.artifact_dir,
            event_log=args.event_log,
        )
    )
    rendered = json_dumps(report) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if report.ready else 2)


if __name__ == "__main__":
    main()
