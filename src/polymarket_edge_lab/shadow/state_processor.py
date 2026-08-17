from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from polymarket_edge_lab.shadow.events import EventEnvelope, NormalizedFill
from polymarket_edge_lab.shadow.state import (
    MarketOnlineState,
    MarketStateQuarantinedError,
    MarketStateSnapshot,
    PairFormation,
    QuarantineRecord,
)
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


@dataclass(frozen=True)
class StateProcessResult:
    processed_fill_count: int
    pair_formation_count: int
    quarantine_count: int


def _snapshot_payload(snapshot: MarketStateSnapshot) -> dict[str, object]:
    return {
        "market_id": snapshot.market_id,
        "up_inventory": str(snapshot.up_inventory),
        "down_inventory": str(snapshot.down_inventory),
        "paired_inventory": str(snapshot.paired_inventory),
        "residual_inventory": str(snapshot.residual_inventory),
        "inventory_imbalance": str(snapshot.inventory_imbalance),
        "cumulative_paired_quantity": str(snapshot.cumulative_paired_quantity),
        "applied_fill_count": snapshot.applied_fill_count,
        "last_source_trade_id": snapshot.last_source_trade_id,
        "quarantined": snapshot.quarantined,
        "quarantine_reason": snapshot.quarantine_reason,
    }


def _pair_payload(
    pair: PairFormation, normalized_fill_event_id: str, index: int
) -> dict[str, object]:
    return {
        "normalized_fill_event_id": normalized_fill_event_id,
        "pair_index": index,
        "market_id": pair.market_id,
        "completing_source_trade_id": pair.completing_source_trade_id,
        "up_source_trade_id": pair.up_source_trade_id,
        "down_source_trade_id": pair.down_source_trade_id,
        "paired_shares": str(pair.paired_shares),
        "up_price": str(pair.up_price),
        "down_price": str(pair.down_price),
        "pair_cost": str(pair.pair_cost),
        "lag_seconds": pair.lag_seconds,
        "formed_at_source_timestamp": (pair.formed_at_source_timestamp.astimezone(UTC).isoformat()),
        "formed_at_receive_timestamp": (
            pair.formed_at_receive_timestamp.astimezone(UTC).isoformat()
        ),
    }


def _quarantine_status(fill: NormalizedFill, exc: MarketStateQuarantinedError) -> str:
    if exc.record.source_trade_id == fill.source_trade_id:
        return "quarantined"
    return "blocked_quarantined"


class LiveStateProcessor:
    """Consume durable normalized fills and append deterministic state outputs."""

    def __init__(self, *, run_id: str, store: AppendOnlyEventStore) -> None:
        self.run_id = run_id
        self.store = store
        self._states: dict[str, MarketOnlineState] = {}
        self._processed_fill_event_ids: set[str] = set()
        self._persisted_pairs: set[tuple[str, int]] = set()
        self._persisted_quarantines: set[str] = set()
        self._pending_restore_records: list[dict[str, object]] = []
        self._restore()
        self._read_offset = self.store.end_offset()

    def _restore(self) -> None:
        records = list(self.store.iter_records())
        fills: dict[str, NormalizedFill] = {}
        fill_records: list[dict[str, object]] = []
        applications: list[tuple[str, str]] = []
        for record in records:
            event_type = record.get("event_type")
            payload = record.get("payload")
            if event_type == "normalized_fill" and isinstance(payload, dict):
                event_id = str(record["event_id"])
                fills[event_id] = NormalizedFill.from_payload(payload)
                fill_records.append(record)
            elif event_type == "pair_formation" and isinstance(payload, dict):
                self._persisted_pairs.add(
                    (str(payload["normalized_fill_event_id"]), int(payload["pair_index"]))
                )
            elif event_type == "state_quarantine" and isinstance(payload, dict):
                self._persisted_quarantines.add(str(payload["normalized_fill_event_id"]))
            elif event_type == "state_application" and isinstance(payload, dict):
                applications.append(
                    (str(payload["normalized_fill_event_id"]), str(payload["status"]))
                )

        for fill_event_id, expected_status in applications:
            fill = fills.get(fill_event_id)
            if fill is None:
                raise ValueError(f"state application references missing fill {fill_event_id}")
            state = self._states.setdefault(fill.market_id, MarketOnlineState(fill.market_id))
            try:
                state.apply(fill)
                actual_status = "applied"
            except MarketStateQuarantinedError as exc:
                actual_status = _quarantine_status(fill, exc)
            if actual_status != expected_status:
                raise ValueError(
                    f"state application status mismatch for {fill_event_id}: "
                    f"expected {expected_status}, derived {actual_status}"
                )
            self._processed_fill_event_ids.add(fill_event_id)

        self._pending_restore_records = [
            record
            for record in fill_records
            if str(record["event_id"]) not in self._processed_fill_event_ids
        ]

    def process_pending(self) -> StateProcessResult:
        tail_records, next_offset = self.store.read_records_from(self._read_offset)
        records = self._pending_restore_records + tail_records
        self._pending_restore_records = []
        self._read_offset = next_offset
        processed = 0
        pair_count = 0
        quarantine_count = 0
        for record in records:
            if record.get("event_type") != "normalized_fill":
                continue
            fill_event_id = str(record["event_id"])
            if fill_event_id in self._processed_fill_event_ids:
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("normalized_fill payload must be an object")
            fill = NormalizedFill.from_payload(payload)
            state = self._states.setdefault(fill.market_id, MarketOnlineState(fill.market_id))
            status = "applied"
            try:
                pairs = state.apply(fill)
            except MarketStateQuarantinedError as exc:
                pairs = []
                status = _quarantine_status(fill, exc)
                if status == "quarantined" and fill_event_id not in self._persisted_quarantines:
                    self._append_quarantine(fill_event_id, exc.record, fill.receive_timestamp)
                    self._persisted_quarantines.add(fill_event_id)
                    quarantine_count += 1

            for index, pair in enumerate(pairs):
                key = (fill_event_id, index)
                if key in self._persisted_pairs:
                    continue
                self._append_pair(fill_event_id, pair, index)
                self._persisted_pairs.add(key)
                pair_count += 1

            self._append_application(
                normalized_fill_event_id=fill_event_id,
                fill=fill,
                status=status,
                snapshot=state.snapshot(),
            )
            self._processed_fill_event_ids.add(fill_event_id)
            processed += 1

        return StateProcessResult(processed, pair_count, quarantine_count)

    def snapshot(self, market_id: str) -> MarketStateSnapshot | None:
        state = self._states.get(market_id)
        return None if state is None else state.snapshot()

    def _append_pair(self, fill_event_id: str, pair: PairFormation, index: int) -> None:
        sequence = self.store.next_sequence()
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="pair_formation",
                event_id=f"{self.run_id}:{sequence}",
                run_id=self.run_id,
                sequence=sequence,
                created_at=pair.formed_at_receive_timestamp,
                payload=_pair_payload(pair, fill_event_id, index),
            )
        )

    def _append_quarantine(
        self, fill_event_id: str, record: QuarantineRecord, observed_at: datetime
    ) -> None:
        sequence = self.store.next_sequence()
        payload = asdict(record)
        payload["normalized_fill_event_id"] = fill_event_id
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="state_quarantine",
                event_id=f"{self.run_id}:{sequence}",
                run_id=self.run_id,
                sequence=sequence,
                created_at=observed_at,
                payload=payload,
            )
        )

    def _append_application(
        self,
        *,
        normalized_fill_event_id: str,
        fill: NormalizedFill,
        status: str,
        snapshot: MarketStateSnapshot,
    ) -> None:
        sequence = self.store.next_sequence()
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="state_application",
                event_id=f"{self.run_id}:{sequence}",
                run_id=self.run_id,
                sequence=sequence,
                created_at=fill.receive_timestamp,
                payload={
                    "normalized_fill_event_id": normalized_fill_event_id,
                    "source_trade_id": fill.source_trade_id,
                    "market_id": fill.market_id,
                    "status": status,
                    "snapshot": _snapshot_payload(snapshot),
                },
            )
        )
