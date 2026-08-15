from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pytest
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.pipeline import Pipeline

from polymarket_edge_lab.analysis.stage3g_models import MODEL_FEATURES
from polymarket_edge_lab.shadow.events import EventEnvelope
from polymarket_edge_lab.shadow.scorer import MODEL_NAMES, LiveShadowScorer, load_frozen_models
from polymarket_edge_lab.shadow.store import AppendOnlyEventStore

RUN_ID = "run-score"
MARKET = "0x" + "1" * 64
NOW = datetime(2026, 8, 15, 12, 2, 10, tzinfo=UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(tmp_path: Path) -> Path:
    root = tmp_path / "models"
    rows: list[dict[str, object]] = []
    for name in MODEL_NAMES:
        model_dir = root / name
        model_dir.mkdir(parents=True)
        regressor = Pipeline([("model", DummyRegressor(strategy="constant", constant=0.97))])
        classifier = Pipeline([("model", DummyClassifier(strategy="prior"))])
        width = len(MODEL_FEATURES[name])
        matrix = [[0.0] * width, [1.0] * width]
        regressor.fit(matrix, [0.9, 1.0])
        classifier.fit(matrix, [0, 1])
        regressor_path = model_dir / "regressor.joblib"
        classifier_path = model_dir / "classifier.joblib"
        joblib.dump(regressor, regressor_path)
        joblib.dump(classifier, classifier_path)
        rows.append(
            {
                "model_name": name,
                "features": list(MODEL_FEATURES[name]),
                "regressor_sha256": _sha256(regressor_path),
                "classifier_sha256": _sha256(classifier_path),
                "preprocessing_fingerprint": "a" * 64,
            }
        )
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": "m4a-model-manifest-v1", "models": rows}),
        encoding="utf-8",
    )
    return root


def _snapshot(store: AppendOnlyEventStore) -> str:
    features = {feature: 0.0 for feature in MODEL_FEATURES["hgb_all_pre_event"]}
    sequence = store.next_sequence()
    event_id = f"{RUN_ID}:{sequence}"
    store.append(
        EventEnvelope(
            schema_version="m4a-event-v1",
            event_type="feature_snapshot",
            event_id=event_id,
            run_id=RUN_ID,
            sequence=sequence,
            created_at=NOW,
            payload={
                "feature_schema_version": "m4a-stage3g-feature-v1",
                "model_name": "hgb_all_pre_event",
                "market_id": MARKET,
                "market_slug": "btc-updown-5m-1786795200",
                "up_token_id": "up",
                "down_token_id": "down",
                "event_epoch": int(NOW.timestamp()),
                "as_of_sequence": sequence - 1,
                "feature_order": list(MODEL_FEATURES["hgb_all_pre_event"]),
                "features": features,
                "btc_reference_epoch": int(NOW.timestamp()) - 10,
                "btc_age_seconds": 10,
                "btc_observed_at": NOW.isoformat(),
                "target_source_last_ok": NOW.isoformat(),
                "target_source_age_seconds": 0,
                "max_target_source_timestamp": None,
                "max_deterministic_fill_key": None,
            },
        )
    )
    return event_id


def test_loader_rejects_tampered_artifact(tmp_path: Path) -> None:
    root = _artifacts(tmp_path)
    path = root / "hgb_all_pre_event" / "regressor.joblib"
    path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="regressor fingerprint mismatch"):
        load_frozen_models(root)


def test_scorer_emits_all_frozen_outputs_and_is_restart_idempotent(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    store = AppendOnlyEventStore(tmp_path / "events.ndjson")
    snapshot_id = _snapshot(store)
    ticks = iter([100.0, 100.1, 100.2])
    scorer = LiveShadowScorer(
        run_id=RUN_ID,
        store=store,
        artifact_dir=artifacts,
        clock=lambda: NOW,
        monotonic_clock=lambda: next(ticks),
    )

    results = scorer.process_pending()

    assert len(results) == 1
    assert results[0].feature_snapshot_event_id == snapshot_id
    records = list(store.iter_records())
    assert [record["event_type"] for record in records[-2:]] == ["score_attempt", "prediction"]
    payload = records[-1]["payload"]
    assert isinstance(payload, dict)
    outputs = payload["model_outputs"]
    assert isinstance(outputs, dict)
    assert set(outputs) == set(MODEL_NAMES)
    primary = outputs["hgb_all_pre_event"]
    assert isinstance(primary, dict)
    assert primary["predicted_pair_cost"] == pytest.approx(0.97)
    assert primary["favorable_probability"] == pytest.approx(0.5)
    assert payload["event_conditioned_reconstruction"] is False
    assert payload["advancement_eligible_candidate"] is True

    restarted = LiveShadowScorer(run_id=RUN_ID, store=store, artifact_dir=artifacts)
    assert restarted.process_pending() == []
