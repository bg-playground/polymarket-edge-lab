from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

MODEL_NAMES = (
    "hgb_all_pre_event",
    "hgb_timing_inventory",
    "linear_timing_inventory",
    "hgb_timing_inventory_btc60",
)
PRIMARY_MODEL_NAME = "hgb_all_pre_event"
SCORE_SCHEMA_VERSION = "m4a-shadow-score-v1"
Clock = Callable[[], datetime]
MonotonicClock = Callable[[], float]


@dataclass(frozen=True)
class LoadedFrozenModel:
    name: str
    features: tuple[str, ...]
    regressor: Pipeline
    classifier: Pipeline
    regressor_sha256: str
    classifier_sha256: str
    preprocessing_fingerprint: str

    @property
    def artifact_fingerprint(self) -> str:
        encoded = "|".join(
            (
                self.name,
                self.regressor_sha256,
                self.classifier_sha256,
                self.preprocessing_fingerprint,
            )
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ShadowScoreResult:
    feature_snapshot_event_id: str
    prediction_event_id: str
    score_id: str


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_frozen_models(artifact_dir: Path) -> dict[str, LoadedFrozenModel]:
    """Load the four frozen Stage 3G artifacts only after fingerprint verification."""
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "m4a-model-manifest-v1":
        raise ValueError("unsupported frozen model manifest schema")
    rows = manifest.get("models")
    if not isinstance(rows, list):
        raise ValueError("frozen model manifest models must be a list")
    by_name = {
        str(row.get("model_name")): row
        for row in rows
        if isinstance(row, dict) and row.get("model_name") is not None
    }
    if set(by_name) != set(MODEL_NAMES):
        raise ValueError("frozen model manifest must contain exactly the Stage 3G model set")

    loaded: dict[str, LoadedFrozenModel] = {}
    for name in MODEL_NAMES:
        metadata = by_name[name]
        features = tuple(str(value) for value in metadata.get("features", []))
        if features != MODEL_FEATURES[name]:
            raise ValueError(f"frozen feature contract mismatch for {name}")
        model_dir = artifact_dir / name
        regressor_path = model_dir / "regressor.joblib"
        classifier_path = model_dir / "classifier.joblib"
        regressor_sha = _sha256(regressor_path)
        classifier_sha = _sha256(classifier_path)
        if regressor_sha != str(metadata.get("regressor_sha256")):
            raise ValueError(f"regressor fingerprint mismatch for {name}")
        if classifier_sha != str(metadata.get("classifier_sha256")):
            raise ValueError(f"classifier fingerprint mismatch for {name}")
        loaded[name] = LoadedFrozenModel(
            name=name,
            features=features,
            regressor=joblib.load(regressor_path),
            classifier=joblib.load(classifier_path),
            regressor_sha256=regressor_sha,
            classifier_sha256=classifier_sha,
            preprocessing_fingerprint=str(metadata["preprocessing_fingerprint"]),
        )
    return loaded


class LiveShadowScorer:
    """Turn durable causal feature snapshots into immutable frozen-model predictions."""

    def __init__(
        self,
        *,
        run_id: str,
        store: AppendOnlyEventStore,
        artifact_dir: Path,
        clock: Clock = _utc_now,
        monotonic_clock: MonotonicClock = time.monotonic,
    ) -> None:
        self.run_id = run_id
        self.store = store
        self.models = load_frozen_models(artifact_dir)
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._scored = self._load_scored_snapshot_ids()

    def process_pending(self) -> list[ShadowScoreResult]:
        results: list[ShadowScoreResult] = []
        for record in list(self.store.iter_records()):
            if record.get("event_type") != "feature_snapshot":
                continue
            snapshot_id = str(record["event_id"])
            if snapshot_id in self._scored:
                continue
            results.append(self._score_snapshot(record))
            self._scored.add(snapshot_id)
        return results

    def _score_snapshot(self, record: dict[str, object]) -> ShadowScoreResult:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("feature_snapshot payload must be an object")
        feature_order = tuple(str(value) for value in payload.get("feature_order", []))
        if feature_order != MODEL_FEATURES[PRIMARY_MODEL_NAME]:
            raise ValueError("feature snapshot does not match frozen primary feature contract")
        features = payload.get("features")
        if not isinstance(features, dict):
            raise ValueError("feature snapshot features must be an object")

        score_started_at = self._clock().astimezone(UTC)
        monotonic_started = self._monotonic_clock()
        attempt_sequence = self.store.next_sequence()
        score_id = f"{self.run_id}:score:{attempt_sequence}"
        attempt_event_id = f"{self.run_id}:{attempt_sequence}"
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="score_attempt",
                event_id=attempt_event_id,
                run_id=self.run_id,
                sequence=attempt_sequence,
                created_at=score_started_at,
                payload={
                    "score_schema_version": SCORE_SCHEMA_VERSION,
                    "score_id": score_id,
                    "feature_snapshot_event_id": str(record["event_id"]),
                    "market_id": str(payload["market_id"]),
                    "event_epoch": int(str(payload["event_epoch"])),
                    "monotonic_started": monotonic_started,
                },
            )
        )

        outputs: dict[str, object] = {}
        fingerprints: dict[str, object] = {}
        for name in MODEL_NAMES:
            model = self.models[name]
            matrix = [
                [
                    float(features[feature]) if features.get(feature) is not None else float("nan")
                    for feature in model.features
                ]
            ]
            pair_cost = float(model.regressor.predict(matrix)[0])
            favorable_probability = float(model.classifier.predict_proba(matrix)[0, 1])
            outputs[name] = {
                "predicted_pair_cost": pair_cost,
                "favorable_probability": favorable_probability,
            }
            fingerprints[name] = {
                "artifact_fingerprint": model.artifact_fingerprint,
                "regressor_sha256": model.regressor_sha256,
                "classifier_sha256": model.classifier_sha256,
                "preprocessing_fingerprint": model.preprocessing_fingerprint,
            }

        write_started_at = self._clock().astimezone(UTC)
        prediction_sequence = self.store.next_sequence()
        prediction_event_id = f"{self.run_id}:{prediction_sequence}"
        prediction_payload: dict[str, object] = {
            "score_schema_version": SCORE_SCHEMA_VERSION,
            "score_id": score_id,
            "score_attempt_event_id": attempt_event_id,
            "feature_snapshot_event_id": str(record["event_id"]),
            "market_id": str(payload["market_id"]),
            "market_slug": str(payload["market_slug"]),
            "up_token_id": str(payload["up_token_id"]),
            "down_token_id": str(payload["down_token_id"]),
            "score_timestamp": score_started_at.isoformat(),
            "event_epoch": int(str(payload["event_epoch"])),
            "max_target_source_timestamp": payload.get("max_target_source_timestamp"),
            "max_deterministic_fill_key": payload.get("max_deterministic_fill_key"),
            "btc_reference_epoch": payload.get("btc_reference_epoch"),
            "btc_observed_at": payload.get("btc_observed_at"),
            "target_source_last_ok": payload.get("target_source_last_ok"),
            "feature_schema_version": payload.get("feature_schema_version"),
            "feature_as_of_sequence": payload.get("as_of_sequence"),
            "model_artifacts": fingerprints,
            "model_outputs": outputs,
            "input_freshness": {
                "btc_age_seconds": payload.get("btc_age_seconds"),
                "target_source_age_seconds": payload.get("target_source_age_seconds"),
            },
            "event_conditioned_reconstruction": False,
            "advancement_eligible_candidate": True,
            "monotonic_started": monotonic_started,
            "monotonic_before_write": self._monotonic_clock(),
            "write_started_at": write_started_at.isoformat(),
        }
        self.store.append(
            EventEnvelope(
                schema_version="m4a-event-v1",
                event_type="prediction",
                event_id=prediction_event_id,
                run_id=self.run_id,
                sequence=prediction_sequence,
                created_at=write_started_at,
                payload=prediction_payload,
            )
        )
        return ShadowScoreResult(str(record["event_id"]), prediction_event_id, score_id)

    def _load_scored_snapshot_ids(self) -> set[str]:
        result: set[str] = set()
        for record in self.store.iter_records():
            if record.get("event_type") != "prediction":
                continue
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("feature_snapshot_event_id") is not None:
                result.add(str(payload["feature_snapshot_event_id"]))
        return result
