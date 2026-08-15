from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from polymarket_edge_lab.shadow.events import EventEnvelope, EventType
from polymarket_edge_lab.shadow.feature_builder import LiveStage3GFeatureBuilder
from polymarket_edge_lab.shadow.replay import replay_arrival_time
from polymarket_edge_lab.shadow.scorer import MODEL_NAMES, load_frozen_models
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore


@dataclass(frozen=True)
class BoundedReplayAuditResult:
    feature_snapshot_count: int
    prediction_count: int
    outcome_label_count: int
    score_binding_count: int
    pair_formation_count: int


def _created_at(record: dict[str, object]) -> datetime:
    return datetime.fromisoformat(str(record["created_at"]))


def _envelope(record: dict[str, object]) -> EventEnvelope:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("replay record payload must be an object")
    event_type = cast(EventType, str(record["event_type"]))
    supersedes = record.get("supersedes_event_id")
    return EventEnvelope(
        schema_version=str(record["schema_version"]),
        event_type=event_type,
        event_id=str(record["event_id"]),
        run_id=str(record["run_id"]),
        sequence=int(str(record["sequence"])),
        created_at=_created_at(record),
        payload=payload,
        supersedes_event_id=None if supersedes is None else str(supersedes),
    )


def _assert_close(actual: object, expected: object, tolerance: float) -> None:
    actual_value = float(str(actual))
    expected_value = float(str(expected))
    if math.isnan(actual_value) and math.isnan(expected_value):
        return
    if not math.isclose(actual_value, expected_value, rel_tol=tolerance, abs_tol=tolerance):
        raise ValueError(f"numeric replay mismatch: expected {expected}, got {actual}")


def _rebuild_feature_snapshot(
    records: list[dict[str, object]], snapshot: dict[str, object]
) -> dict[str, object]:
    payload = snapshot.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("feature_snapshot payload must be an object")
    as_of_sequence = int(str(payload["as_of_sequence"]))
    with TemporaryDirectory(prefix="m4a-replay-") as temp_dir:
        temp_store = AppendOnlyEventStore(Path(temp_dir) / "events.ndjson")
        for record in records:
            sequence = int(str(record["sequence"]))
            if sequence > as_of_sequence:
                break
            temp_store.append(_envelope(record))
        builder = LiveStage3GFeatureBuilder(
            run_id=str(snapshot["run_id"]),
            store=temp_store,
        )
        result = builder.build_tick(
            market_id=str(payload["market_id"]),
            tick_time=datetime.fromisoformat(str(payload["tick_timestamp"])),
            as_of_sequence=as_of_sequence,
        )
        if not result.scorable:
            raise ValueError(
                f"replay made persisted feature snapshot unscorable: {result.reason_code}"
            )
        rebuilt = list(temp_store.iter_records())[-1]
        rebuilt_payload = rebuilt.get("payload")
        if not isinstance(rebuilt_payload, dict):
            raise ValueError("rebuilt feature_snapshot payload must be an object")
        return rebuilt_payload


def _audit_features(records: list[dict[str, object]]) -> int:
    count = 0
    for record in records:
        if record.get("event_type") != "feature_snapshot":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("feature_snapshot payload must be an object")
        rebuilt = _rebuild_feature_snapshot(records, record)
        if payload.get("feature_order") != rebuilt.get("feature_order"):
            raise ValueError("feature order replay mismatch")
        if payload.get("features") != rebuilt.get("features"):
            raise ValueError("feature values replay mismatch")
        for key in (
            "btc_reference_epoch",
            "btc_reference_price",
            "max_target_source_timestamp",
            "max_target_receive_timestamp",
            "max_deterministic_fill_key",
            "applied_buy_fill_count",
        ):
            if payload.get(key) != rebuilt.get(key):
                raise ValueError(f"feature provenance replay mismatch for {key}")
        count += 1
    return count


def _audit_predictions(
    records: list[dict[str, object]], artifact_dir: Path, tolerance: float
) -> int:
    models = load_frozen_models(artifact_dir)
    snapshots = {
        str(record["event_id"]): record
        for record in records
        if record.get("event_type") == "feature_snapshot"
    }
    count = 0
    for record in records:
        if record.get("event_type") != "prediction":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("prediction payload must be an object")
        snapshot_id = str(payload["feature_snapshot_event_id"])
        snapshot = snapshots.get(snapshot_id)
        if snapshot is None:
            raise ValueError(f"prediction references missing snapshot {snapshot_id}")
        if int(str(snapshot["sequence"])) >= int(str(record["sequence"])):
            raise ValueError("prediction does not follow its feature snapshot")
        snapshot_payload = snapshot.get("payload")
        if not isinstance(snapshot_payload, dict):
            raise ValueError("feature_snapshot payload must be an object")
        features = snapshot_payload.get("features")
        if not isinstance(features, dict):
            raise ValueError("feature_snapshot features must be an object")
        outputs = payload.get("model_outputs")
        if not isinstance(outputs, dict):
            raise ValueError("prediction model_outputs must be an object")
        for name in MODEL_NAMES:
            model = models[name]
            matrix = [
                [
                    float(features[feature]) if features.get(feature) is not None else float("nan")
                    for feature in model.features
                ]
            ]
            expected_pair_cost = model.regressor.predict(matrix)[0]
            expected_probability = model.classifier.predict_proba(matrix)[0, 1]
            output = outputs.get(name)
            if not isinstance(output, dict):
                raise ValueError(f"prediction output missing for {name}")
            _assert_close(output["predicted_pair_cost"], expected_pair_cost, tolerance)
            _assert_close(output["favorable_probability"], expected_probability, tolerance)
        count += 1
    return count


def _eligible_prediction(record: dict[str, object], market_id: str) -> bool:
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


def _expected_binding_prediction(
    records: list[dict[str, object]], pair: dict[str, object]
) -> str | None:
    payload = pair.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("pair_formation payload must be an object")
    pair_sequence = int(str(pair["sequence"]))
    source_time = datetime.fromisoformat(str(payload["formed_at_source_timestamp"]))
    boundary_ms = int(source_time.timestamp()) * 1000
    market_id = str(payload["market_id"])
    candidates = [
        record
        for record in records
        if int(str(record["sequence"])) < pair_sequence
        and _eligible_prediction(record, market_id)
        and int(_created_at(record).timestamp() * 1000) < boundary_ms
    ]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda record: (_created_at(record), int(str(record["sequence"]))),
    )
    return str(selected["event_id"])


def _audit_outcomes_and_bindings(records: list[dict[str, object]]) -> tuple[int, int, int]:
    pairs = {
        str(record["event_id"]): record
        for record in records
        if record.get("event_type") == "pair_formation"
    }
    outcomes: dict[str, dict[str, object]] = {}
    bindings: dict[str, dict[str, object]] = {}
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        pair_id = payload.get("pair_formation_event_id")
        if pair_id is None:
            continue
        if record.get("event_type") == "outcome_label":
            outcomes[str(pair_id)] = record
        elif record.get("event_type") == "score_binding":
            bindings[str(pair_id)] = record

    if set(outcomes) != set(pairs):
        raise ValueError("outcome-label coverage does not match pair formations")
    if set(bindings) != set(pairs):
        raise ValueError("score-binding coverage does not match pair formations")

    for pair_id, pair in pairs.items():
        pair_payload = pair.get("payload")
        outcome_payload = outcomes[pair_id].get("payload")
        binding_payload = bindings[pair_id].get("payload")
        if not isinstance(pair_payload, dict):
            raise ValueError("pair_formation payload must be an object")
        if not isinstance(outcome_payload, dict):
            raise ValueError("outcome_label payload must be an object")
        if not isinstance(binding_payload, dict):
            raise ValueError("score_binding payload must be an object")
        pair_cost = float(pair_payload["pair_cost"])
        if float(outcome_payload["pair_cost"]) != pair_cost:
            raise ValueError("outcome pair_cost replay mismatch")
        if bool(outcome_payload["favorable"]) != (pair_cost < 1.0):
            raise ValueError("outcome favorable replay mismatch")
        expected_prediction = _expected_binding_prediction(records, pair)
        actual_prediction = binding_payload.get("prediction_event_id")
        if actual_prediction != expected_prediction:
            raise ValueError("strict score binding replay mismatch")
        expected_status = (
            "unbound_no_strictly_prior_score"
            if expected_prediction is None
            else "bound_strictly_prior_score"
        )
        if binding_payload.get("status") != expected_status:
            raise ValueError("score binding status replay mismatch")

    return len(pairs), len(outcomes), len(bindings)


def audit_bounded_shadow_replay(
    store: AppendOnlyEventStore,
    *,
    artifact_dir: Path,
    numeric_tolerance: float = 1e-12,
) -> BoundedReplayAuditResult:
    """Reproduce bounded Milestone 4A live decisions without consulting external APIs."""
    if numeric_tolerance < 0:
        raise ValueError("numeric_tolerance must be non-negative")
    replay_arrival_time(store)
    records = list(store.iter_records())
    feature_count = _audit_features(records)
    prediction_count = _audit_predictions(records, artifact_dir, numeric_tolerance)
    pair_count, outcome_count, binding_count = _audit_outcomes_and_bindings(records)
    return BoundedReplayAuditResult(
        feature_snapshot_count=feature_count,
        prediction_count=prediction_count,
        outcome_label_count=outcome_count,
        score_binding_count=binding_count,
        pair_formation_count=pair_count,
    )
