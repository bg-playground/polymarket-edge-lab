from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from polymarket_edge_lab.shadow.events import NormalizedFill
from polymarket_edge_lab.shadow.state import MarketOnlineState, MarketStateSnapshot, PairFormation
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


class ReplayResult:
    def __init__(
        self,
        *,
        snapshots: dict[str, MarketStateSnapshot],
        pair_formations: list[PairFormation],
        processed_events: int,
    ) -> None:
        self.snapshots = snapshots
        self.pair_formations = pair_formations
        self.processed_events = processed_events


def replay_arrival_time(store: AppendOnlyEventStore) -> ReplayResult:
    """Replay normalized fills in exact durable append order without external API access."""
    states: dict[str, MarketOnlineState] = {}
    formations: list[PairFormation] = []
    processed = 0

    for expected_sequence, record in enumerate(store.iter_records()):
        sequence = record.get("sequence")
        if sequence != expected_sequence:
            raise ValueError(
                f"replay sequence mismatch: expected {expected_sequence}, got {sequence}"
            )
        processed += 1
        if record.get("event_type") != "normalized_fill":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("normalized_fill payload must be an object")
        fill = NormalizedFill.from_payload(payload)
        state = states.setdefault(fill.market_id, MarketOnlineState(fill.market_id))
        formations.extend(state.apply(fill))

    snapshots = {market_id: state.snapshot() for market_id, state in states.items()}
    return ReplayResult(
        snapshots=snapshots,
        pair_formations=formations,
        processed_events=processed,
    )


def canonical_fill_key(fill: NormalizedFill) -> tuple[datetime, str, str]:
    """Historical/event-time deterministic key; local ingest ID is only a final tie-breaker."""
    return (fill.source_timestamp, fill.source_trade_id, fill.local_ingest_id)


def group_canonical_fills(
    fills: list[NormalizedFill],
) -> dict[str, list[NormalizedFill]]:
    grouped: dict[str, list[NormalizedFill]] = defaultdict(list)
    for fill in fills:
        grouped[fill.market_id].append(fill)
    for market_id in grouped:
        grouped[market_id].sort(key=canonical_fill_key)
    return dict(grouped)
