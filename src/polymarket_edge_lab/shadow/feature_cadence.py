from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from polymarket_edge_lab.shadow.feature_builder import (
    DEFAULT_TICK_INTERVAL_SECONDS,
    LiveStage3GFeatureBuilder,
)
from polymarket_edge_lab.shadow.market_metadata import EligibleMarketMetadata
from polymarket_edge_lab.shadow.scorer import LiveShadowScorer
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def active_market_ids(
    store: AppendOnlyEventStore,
    *,
    tick_time: datetime,
    as_of_sequence: int,
) -> list[str]:
    latest: dict[str, EligibleMarketMetadata | None] = {}
    for record in store.iter_records():
        sequence = int(str(record["sequence"]))
        if sequence > as_of_sequence:
            break
        if record.get("event_type") != "market_metadata":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        market_id = str(payload.get("condition_id") or "")
        if not market_id:
            continue
        metadata_payload = payload.get("metadata")
        if payload.get("eligible") is True and isinstance(metadata_payload, dict):
            latest[market_id] = EligibleMarketMetadata.from_payload(metadata_payload)
        else:
            latest[market_id] = None

    epoch = int(tick_time.astimezone(UTC).timestamp())
    active: list[str] = []
    for market_id, metadata in latest.items():
        if metadata is None:
            continue
        if metadata.market_start_epoch <= epoch < metadata.market_end_epoch:
            active.append(market_id)
    return sorted(active)


class LiveFeatureCadence:
    """Drive 1 Hz feature attempts and optional frozen shadow scoring."""

    def __init__(
        self,
        *,
        builder: LiveStage3GFeatureBuilder,
        store: AppendOnlyEventStore,
        scorer: LiveShadowScorer | None = None,
    ) -> None:
        self.builder = builder
        self.store = store
        self.scorer = scorer

    def tick(self, *, tick_time: datetime) -> None:
        cutoff_sequence = self.store.next_sequence() - 1
        for market_id in active_market_ids(
            self.store,
            tick_time=tick_time,
            as_of_sequence=cutoff_sequence,
        ):
            self.builder.build_tick(
                market_id=market_id,
                tick_time=tick_time,
                as_of_sequence=cutoff_sequence,
            )
        if self.scorer is not None:
            self.scorer.process_pending()

    async def run_forever(
        self,
        *,
        tick_interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS,
        clock: Clock = _utc_now,
    ) -> None:
        if tick_interval_seconds <= 0:
            raise ValueError("tick_interval_seconds must be positive")
        while True:
            started = asyncio.get_running_loop().time()
            self.tick(tick_time=clock())
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, tick_interval_seconds - elapsed))
