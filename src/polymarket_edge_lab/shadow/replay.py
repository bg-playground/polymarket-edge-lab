from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from polymarket_edge_lab.shadow.events import NormalizedFill
from polymarket_edge_lab.shadow.state import (
    MarketOnlineState,
    MarketStateQuarantinedError,
    MarketStateSnapshot,
    PairFormation,
    QuarantineRecord,
)
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


class ReplayResult:
    def __init__(
        self,
        *,
        snapshots: dict[str, MarketStateSnapshot],
        pair_formations: list[PairFormation],
        quarantines: list[QuarantineRecord],
        processed_events: int,
    ) -> None:
        self.snapshots = snapshots
        self.pair_formations = pair_formations
        self.quarantines = quarantines
        self.processed_events = processed_events


def replay_arrival_time(store: AppendOnlyEventStore) -> ReplayResult:
    """Replay durable append order and verify recorded quarantine decisions."""
    states: dict[str, MarketOnlineState] = {}
    formations: list[PairFormation] = []
    quarantines: list[QuarantineRecord] = []
    pending_quarantine: QuarantineRecord | None = None
    processed = 0

    for expected_sequence, record in enumerate(store.iter_records()):
        sequence = record.get("sequence")
        if sequence != expected_sequence:
            raise ValueError(
                f"replay sequence mismatch: expected {expected_sequence}, got {sequence}"
            )
        processed += 1
        event_type = record.get("event_type")
        payload = record.get("payload")
        if event_type == "normalized_fill":
            if not isinstance(payload, dict):
                raise ValueError("normalized_fill payload must be an object")
            fill = NormalizedFill.from_payload(payload)
            state = states.setdefault(fill.market_id, MarketOnlineState(fill.market_id))
            try:
                formations.extend(state.apply(fill))
            except MarketStateQuarantinedError as exc:
                if not quarantines or quarantines[-1] != exc.record:
                    quarantines.append(exc.record)
                pending_quarantine = exc.record
            continue
        if event_type == "state_quarantine":
            if not isinstance(payload, dict):
                raise ValueError("state_quarantine payload must be an object")
            persisted = QuarantineRecord(
                market_id=str(payload["market_id"]),
                source_trade_id=str(payload["source_trade_id"]),
                reason_code=str(payload["reason_code"]),
                detail=str(payload["detail"]),
            )
            if pending_quarantine != persisted:
                raise ValueError("persisted quarantine does not match replay-derived quarantine")
            pending_quarantine = None

    if pending_quarantine is not None:
        raise ValueError("replay-derived quarantine is missing durable state_quarantine record")
    snapshots = {market_id: state.snapshot() for market_id, state in states.items()}
    return ReplayResult(
        snapshots=snapshots,
        pair_formations=formations,
        quarantines=quarantines,
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
