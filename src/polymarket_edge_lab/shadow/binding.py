from __future__ import annotations

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
    return max(candidates, key=lambda record: (_created_at(record), int(str(record["sequence"]))))


class ProspectiveOutcomeBinder:
    """Append Stage 3G labels and conservative prospective score bindings for pair rows."""

    def __init__(self, *, run_id: str, store: AppendOnlyEventStore) -> None:
        self.run_id = run_id
        self.store = store
        self._processed_pair_event_ids = self._load_processed_pair_ids()

    def process_pending(self) -> BindingProcessResult:
        records = list(self.store.iter_records())
        labeled = 0
        bound = 0
        unbound = 0
        for record in records:
            if record.get("event_type") != "pair_formation":
                continue
            pair_event_id = str(record["event_id"])
            if pair_event_id in self._processed_pair_event_ids:
                continue
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
            labeled += 1

            market_id = str(payload["market_id"])
            source_second_epoch = int(formed_at_source.timestamp())
            selected = _latest_strictly_prior_prediction(
                records,
                market_id=market_id,
                source_second_epoch=source_second_epoch,
                pair_sequence=int(str(record["sequence"])),
            )
            self._append_binding(
                pair_event_id=pair_event_id,
                outcome_label_event_id=outcome_event_id,
                market_id=market_id,
                source_second_epoch=source_second_epoch,
                selected_prediction=selected,
                created_at=_created_at(record),
            )
            if selected is None:
                unbound += 1
            else:
                bound += 1
            self._processed_pair_event_ids.add(pair_event_id)

        return BindingProcessResult(labeled, bound, unbound)

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

    def _load_processed_pair_ids(self) -> set[str]:
        processed: set[str] = set()
        for record in self.store.iter_records():
            if record.get("event_type") != "score_binding":
                continue
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("pair_formation_event_id") is not None:
                processed.add(str(payload["pair_formation_event_id"]))
        return processed
