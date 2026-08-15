from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.scorer import MODEL_NAMES
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

EVALUATION_SCHEMA_VERSION = "m4a-frozen-evaluation-v1"
FROZEN_TARGET_ACCOUNT = "0xbf337426aa856996b8bb79b238345dd1a0276bf7"
FROZEN_EVALUATION_START_HOUR_UTC = 12
FROZEN_EVALUATION_END_HOUR_UTC = 18
FROZEN_TARGET_POLL_INTERVAL_SECONDS = 1.0
FROZEN_FEATURE_TICK_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class FrozenEvaluationConfig:
    run_id: str
    repository_commit: str
    artifact_dir: Path
    target_account: str = FROZEN_TARGET_ACCOUNT
    target_poll_interval_seconds: float = FROZEN_TARGET_POLL_INTERVAL_SECONDS
    feature_tick_interval_seconds: float = FROZEN_FEATURE_TICK_INTERVAL_SECONDS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_manifest(config: FrozenEvaluationConfig) -> dict[str, object]:
    manifest_path = config.artifact_dir / "manifest.json"
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

    models: dict[str, object] = {}
    for name in MODEL_NAMES:
        row = by_name[name]
        regressor_path = config.artifact_dir / name / "regressor.joblib"
        classifier_path = config.artifact_dir / name / "classifier.joblib"
        regressor_sha = _sha256(regressor_path)
        classifier_sha = _sha256(classifier_path)
        if regressor_sha != str(row.get("regressor_sha256")):
            raise ValueError(f"regressor fingerprint mismatch for {name}")
        if classifier_sha != str(row.get("classifier_sha256")):
            raise ValueError(f"classifier fingerprint mismatch for {name}")
        models[name] = {
            "regressor_sha256": regressor_sha,
            "classifier_sha256": classifier_sha,
            "preprocessing_fingerprint": str(row["preprocessing_fingerprint"]),
            "training_row_count": int(str(row["training_row_count"])),
            "training_paired_share_weight": float(str(row["training_paired_share_weight"])),
            "source_commit": str(row["source_commit"]),
        }
    return {
        "manifest_sha256": _sha256(manifest_path),
        "manifest_source_commit": str(manifest.get("source_commit") or ""),
        "models": models,
    }


def _validate_config(config: FrozenEvaluationConfig) -> None:
    if not config.run_id.strip():
        raise ValueError("frozen evaluation run_id must not be empty")
    if not config.repository_commit.strip():
        raise ValueError("repository_commit must not be empty")
    if config.target_account.lower() != FROZEN_TARGET_ACCOUNT:
        raise ValueError("frozen evaluation target account mismatch")
    if config.target_poll_interval_seconds != FROZEN_TARGET_POLL_INTERVAL_SECONDS:
        raise ValueError("frozen target poll interval must be exactly 1 second")
    if config.feature_tick_interval_seconds != FROZEN_FEATURE_TICK_INTERVAL_SECONDS:
        raise ValueError("frozen feature tick interval must be exactly 1 second")


def start_frozen_evaluation(
    *,
    store: AppendOnlyEventStore,
    config: FrozenEvaluationConfig,
    started_at: datetime,
) -> str:
    """Append the immutable evaluation-start record before any eligible observation."""
    _validate_config(config)
    if store.next_sequence() != 0:
        raise ValueError("frozen evaluation must start on an empty event log")
    artifacts = _artifact_manifest(config)
    sequence = store.next_sequence()
    event_id = f"{config.run_id}:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type="evaluation_run_start",
            event_id=event_id,
            run_id=config.run_id,
            sequence=sequence,
            created_at=started_at.astimezone(UTC),
            payload={
                "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
                "frozen_evaluation": True,
                "repository_commit": config.repository_commit,
                "target_account": config.target_account.lower(),
                "evaluation_start_hour_utc": FROZEN_EVALUATION_START_HOUR_UTC,
                "evaluation_end_hour_utc": FROZEN_EVALUATION_END_HOUR_UTC,
                "target_poll_interval_seconds": config.target_poll_interval_seconds,
                "feature_tick_interval_seconds": config.feature_tick_interval_seconds,
                "artifact_manifest": artifacts,
            },
        )
    )
    return event_id


def load_frozen_evaluation_start(store: AppendOnlyEventStore) -> dict[str, object]:
    starts = [
        record
        for record in store.iter_records()
        if record.get("event_type") == "evaluation_run_start"
    ]
    if len(starts) != 1:
        raise ValueError("event log must contain exactly one frozen evaluation start")
    start = starts[0]
    if int(str(start["sequence"])) != 0:
        raise ValueError("frozen evaluation start must be sequence zero")
    payload = start.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("evaluation_run_start payload must be an object")
    if payload.get("frozen_evaluation") is not True:
        raise ValueError("event log is not designated frozen_evaluation=true")
    return start


def verify_frozen_evaluation(
    *,
    store: AppendOnlyEventStore,
    config: FrozenEvaluationConfig,
) -> dict[str, object]:
    """Fail closed if the live configuration or model artifacts drift after start."""
    _validate_config(config)
    start = load_frozen_evaluation_start(store)
    if str(start["run_id"]) != config.run_id:
        raise ValueError("frozen evaluation run_id mismatch")
    payload = start["payload"]
    assert isinstance(payload, dict)
    if payload.get("repository_commit") != config.repository_commit:
        raise ValueError("frozen evaluation repository commit drift")
    if payload.get("target_account") != config.target_account.lower():
        raise ValueError("frozen evaluation target account drift")
    if payload.get("target_poll_interval_seconds") != config.target_poll_interval_seconds:
        raise ValueError("frozen evaluation target poll interval drift")
    if payload.get("feature_tick_interval_seconds") != config.feature_tick_interval_seconds:
        raise ValueError("frozen evaluation feature cadence drift")
    if payload.get("artifact_manifest") != _artifact_manifest(config):
        raise ValueError("frozen evaluation artifact manifest drift")
    return start
