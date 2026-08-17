from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

BINDING_SCHEMA_VERSION = "m4a-score-binding-v1"


@dataclass(frozen=True)
class BindingProcessResult:
    labeled_pair_count: int
    bound_pair_count: int
    unbound_pair_count: int


def _created_at(record: dict[str, object]) -> datetime:
    return datetime.fromisoformat(str(record["created_at"])).astimezone(UTC)


def _prediction_is_eligible(record: dict[str, object], market_id: str) -> bool:
    if record.get("event_type") != "prediction":
        return False
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("market_id") or "").lower() == market_id.lower()
        and payload.get("advancement_eligible_candidate") is True
        and payload.get("event_conditioned_reconstruction") is False
    )


def _latest_strictly_prior_prediction(
    records: list[dict[str, object]],
    *,
    market_id: str,
    source_second_epoch: int,
    pair_sequence: int,
) -> dict[str, object] | None:
    boundary_ms = source_second_epoch * 1000
    candidates = [
        record
        for record in records
        if int(str(record["sequence"])) < pair_sequence
        and _prediction_is_eligible(record, market_id)
        and int(_created_at(record).timestamp() * 1000) < boundary_ms
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda record: (_created_at(record), int(str(record["sequence"]))),
    )


class ProspectiveOutcomeBinder:
    """Append Stage 3G labels and conservative prospective score bindings for pair rows."""

    def __init__(self, *, run_id: str, store: AppendOnlyEventStore) -> None:
        self.run_id = run_id
        self.store = store
        self._processed_pair_event_ids: set[str] = set()
        self._prediction_keys: dict[str, list[tuple[datetime, int]]] = {}
        self._prediction_records: dict[str, list[dict[str, object]]] = {}
        self._pending_restore: list[tuple[dict[str, object], dict[str, object] | None]] = []
        self._restore()
        self._read_offset = self.store.end_offset()

    def _restore(self) -> None:
        records = list(self.store.iter_records())
        for record in records:
            if record.get("event_type") != "score_binding":
                continue
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("pair_formation_event_id") is not None:
                self._processed_pair_event_ids.add(str(payload["pair_formation_event_id"]))

        for record in records:
            if record.get("event_type") == "prediction":
                self._index_prediction(record)
                continue
            if record.get("event_type") != "pair_formation":
                continue
            pair_event_id = str(record["event_id"])
            if pair_event_id in self._processed_pair_event_ids:
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("pair_formation payload must be an object")
            formed_at_source = datetime.fromisoformat(
                str(payload["formed_at_source_timestamp"])
            ).astimezone(UTC)
            selected = _latest_strictly_prior_prediction(
                records,
                market_id=str(payload["market_id"]),
                source_second_epoch=int(formed_at_source.timestamp()),
                pair_sequence=int(str(record["sequence"])),
            )
            self._pending_restore.append((record, selected))

    def process_pending(self) -> BindingProcessResult:
        tail_records, next_offset = self.store.read_records_from(self._read_offset)
        self._read_offset = next_offset
        labeled = 0
        bound = 0
        unbound = 0

        for record, selected in self._pending_restore:
            result = self._process_pair(record, selected)
            labeled += 1
            if result:
                bound += 1
            else:
                unbound += 1
        self._pending_restore = []

        for record in tail_records:
            if record.get("event_type") == "prediction":
                self._index_prediction(record)
                continue
            if record.get("event_type") != "pair_formation":
                continue
            pair_event_id = str(record["event_id"])
            if pair_event_id in self._processed_pair_event_ids:
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("pair_formation payload must be an object")
            formed_at_source = datetime.fromisoformat(
                str(payload["formed_at_source_timestamp"])
            ).astimezone(UTC)
            selected = self._latest_indexed_prediction(
                market_id=str(payload["market_id"]),
                source_second_epoch=int(formed_at_source.timestamp()),
            )
            result = self._process_pair(record, selected)
            labeled += 1
            if result:
                bound += 1
            else:
                unbound += 1

        return BindingProcessResult(labeled, bound, unbound)

    def _index_prediction(self, record: dict[str, object]) -> None:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return
        market_id = str(payload.get("market_id") or "")
        if not market_id or not _prediction_is_eligible(record, market_id):
            return
        key = market_id.lower()
        sort_key = (_created_at(record), int(str(record["sequence"])))
        keys = self._prediction_keys.setdefault(key, [])
        records = self._prediction_records.setdefault(key, [])
        insertion = bisect_left(keys, sort_key)
        if insertion < len(keys) and keys[insertion] == sort_key:
            return
        keys.insert(insertion, sort_key)
        records.insert(insertion, record)

    def _latest_indexed_prediction(
        self, *, market_id: str, source_second_epoch: int
    ) -> dict[str, object] | None:
        key = market_id.lower()
        keys = self._prediction_keys.get(key)
        records = self._prediction_records.get(key)
        if not keys or not records:
            return None
        boundary = datetime.fromtimestamp(source_second_epoch, tz=UTC)
        index = bisect_left(keys, (boundary, -1)) - 1
        if index < 0:
            return None
        return records[index]

    def _process_pair(
        self,
        record: dict[str, object],
        selected_prediction: dict[str, object] | None,
    ) -> bool:
        pair_event_id = str(record["event_id"])
        if pair_event_id in self._processed_pair_event_ids:
            return selected_prediction is not None
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("pair_formation payload must be an object")
        pair_cost = Decimal(str(payload["pair_cost"]))
        formed_at_source = datetime.fromisoformat(
            str(payload["formed_at_source_timestamp"])
        ).astimezone(UTC)
        outcome_event_id = self._append_outcome_label(
            pair_event_id=pair_event_id,
            payload=payload,
            pair_cost=pair_cost,
            created_at=_created_at(record),
        )
        market_id = str(payload["market_id"])
        source_second_epoch = int(formed_at_source.timestamp())
        self._append_binding(
            pair_event_id=pair_event_id,
            outcome_label_event_id=outcome_event_id,
            market_id=market_id,
            source_second_epoch=source_second_epoch,
            selected_prediction=selected_prediction,
            created_at=_created_at(record),
        )
        self._processed_pair_event_ids.add(pair_event_id)
        return selected_prediction is not None

    def _append_outcome_label(
        self,
        *,
        pair_event_id: str,
        payload: dict[str, object],
        pair_cost: Decimal,
        created_at: datetime,
    ) -> str:
        sequence = self.store.next_sequence()
        event_id = f"{self.run_id}:{sequence}"
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="outcome_label",
                event_id=event_id,
                run_id=self.run_id,
                sequence=sequence,
                created_at=created_at,
                payload={
                    "binding_schema_version": BINDING_SCHEMA_VERSION,
                    "pair_formation_event_id": pair_event_id,
                    "market_id": str(payload["market_id"]),
                    "normalized_fill_event_id": str(payload["normalized_fill_event_id"]),
                    "pair_index": int(str(payload["pair_index"])),
                    "completing_source_trade_id": str(payload["completing_source_trade_id"]),
                    "paired_shares": str(payload["paired_shares"]),
                    "pair_cost": str(pair_cost),
                    "favorable": pair_cost < Decimal("1.0"),
                    "lag_seconds_label_only": int(str(payload["lag_seconds"])),
                    "formed_at_source_timestamp": str(payload["formed_at_source_timestamp"]),
                    "formed_at_receive_timestamp": str(payload["formed_at_receive_timestamp"]),
                },
            )
        )
        return event_id

    def _append_binding(
        self,
        *,
        pair_event_id: str,
        outcome_label_event_id: str,
        market_id: str,
        source_second_epoch: int,
        selected_prediction: dict[str, object] | None,
        created_at: datetime,
    ) -> None:
        sequence = self.store.next_sequence()
        prediction_payload: dict[str, object] | None = None
        if selected_prediction is not None:
            raw_payload = selected_prediction.get("payload")
            if not isinstance(raw_payload, dict):
                raise ValueError("prediction payload must be an object")
            prediction_payload = raw_payload
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="score_binding",
                event_id=f"{self.run_id}:{sequence}",
                run_id=self.run_id,
                sequence=sequence,
                created_at=created_at,
                payload={
                    "binding_schema_version": BINDING_SCHEMA_VERSION,
                    "pair_formation_event_id": pair_event_id,
                    "outcome_label_event_id": outcome_label_event_id,
                    "market_id": market_id,
                    "source_second_epoch": source_second_epoch,
                    "strict_boundary_epoch_ms": source_second_epoch * 1000,
                    "status": (
                        "bound_strictly_prior_score"
                        if selected_prediction is not None
                        else "unbound_no_strictly_prior_score"
                    ),
                    "prediction_event_id": (
                        None
                        if selected_prediction is None
                        else str(selected_prediction["event_id"])
                    ),
                    "score_id": (
                        None if prediction_payload is None else prediction_payload.get("score_id")
                    ),
                    "score_timestamp": (
                        None
                        if selected_prediction is None
                        else _created_at(selected_prediction).isoformat()
                    ),
                    "event_conditioned_reconstruction": (
                        None
                        if prediction_payload is None
                        else prediction_payload.get("event_conditioned_reconstruction")
                    ),
                    "advancement_eligible_candidate": (
                        None
                        if prediction_payload is None
                        else prediction_payload.get("advancement_eligible_candidate")
                    ),
                },
            )
        )
