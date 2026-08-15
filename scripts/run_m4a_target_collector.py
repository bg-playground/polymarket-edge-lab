#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from polymarket_edge_lab.shadow.store import AppendOnlyEventStore
from polymarket_edge_lab.shadow.target_collector import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    LiveTargetAccountCollector,
)

FROZEN_TARGET_ACCOUNT = "0xbf337426aa856996b8bb79b238345dd1a0276bf7"


async def _run(args: argparse.Namespace) -> None:
    store = AppendOnlyEventStore(args.event_log)
    collector = LiveTargetAccountCollector(
        account=args.account,
        run_id=args.run_id,
        store=store,
        page_limit=args.page_limit,
    )
    await collector.run_forever(poll_interval_seconds=args.poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the read-only Milestone 4A target-account Data API collector"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--account", default=FROZEN_TARGET_ACCOUNT)
    parser.add_argument("--page-limit", type=int, default=500)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
