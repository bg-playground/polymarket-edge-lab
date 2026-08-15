#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from polymarket_edge_lab.shadow.btc_collector import (
    DEFAULT_POLL_INTERVAL_SECONDS as BTC_POLL_INTERVAL_SECONDS,
)
from polymarket_edge_lab.shadow.btc_collector import LiveBtc60Collector
from polymarket_edge_lab.shadow.feature_builder import (
    DEFAULT_TICK_INTERVAL_SECONDS,
    LiveStage3GFeatureBuilder,
)
from polymarket_edge_lab.shadow.market_metadata import LiveMarketMetadataResolver
from polymarket_edge_lab.shadow.state_processor import LiveStateProcessor
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore
from polymarket_edge_lab.shadow.target_collector import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    LiveTargetAccountCollector,
)

FROZEN_TARGET_ACCOUNT = "0xbf337426aa856996b8bb79b238345dd1a0276bf7"


async def _run_state_processor(processor: LiveStateProcessor, interval: float) -> None:
    while True:
        processor.process_pending()
        await asyncio.sleep(interval)


async def _run(args: argparse.Namespace) -> None:
    store = AppendOnlyEventStore(args.event_log)
    metadata_resolver = LiveMarketMetadataResolver(run_id=args.run_id, store=store)
    collector = LiveTargetAccountCollector(
        account=args.account,
        run_id=args.run_id,
        store=store,
        metadata_resolver=metadata_resolver,
        page_limit=args.page_limit,
    )
    state_processor = LiveStateProcessor(run_id=args.run_id, store=store)
    btc_collector = LiveBtc60Collector(run_id=args.run_id, store=store)
    feature_builder = LiveStage3GFeatureBuilder(run_id=args.run_id, store=store)
    await asyncio.gather(
        collector.run_forever(poll_interval_seconds=args.poll_interval),
        _run_state_processor(state_processor, args.poll_interval),
        btc_collector.run_forever(poll_interval_seconds=args.btc_poll_interval),
        feature_builder.run_forever(tick_interval_seconds=args.feature_tick_interval),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the read-only Milestone 4A target/state/BTC/feature pipeline"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--account", default=FROZEN_TARGET_ACCOUNT)
    parser.add_argument("--page-limit", type=int, default=500)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--btc-poll-interval", type=float, default=BTC_POLL_INTERVAL_SECONDS)
    parser.add_argument(
        "--feature-tick-interval",
        type=float,
        default=DEFAULT_TICK_INTERVAL_SECONDS,
    )
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
